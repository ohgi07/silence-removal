"""keep 구간대로 잘라 이어붙여 출력 파일을 만든다."""
from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable

# 진행 콜백: 0.0~1.0 사이의 완료 비율을 받는다.
ProgressCallback = Callable[[float], None]

# 구간 처리는 전체 진행의 이 비율까지만 채우고, 남은 몫은 최종 concat 단계에 둔다.
_SEGMENT_SHARE = 0.95

from .ffmpeg_utils import (
    detect_encoder,
    detect_hwaccel,
    get_audio_bitrate,
    run_ffmpeg,
)
from .segments import Interval

# 무손실 출력이 가능한 오디오 전용 컨테이너 → 무손실 코덱.
_LOSSLESS_AUDIO_CODECS = {".wav": "pcm_s16le", ".flac": "flac"}


# 인코더별 "품질 고정" 설정. 값이 낮을수록 고화질(용량 큼). 목표는 시각적
# 무손실 근처 — 원본 비트레이트에 맞춰 필요한 만큼만 데이터를 쓴다. 하드웨어
# 인코더는 품질을 지정하지 않으면 기본 저비트레이트로 인코딩되어 과압축된다.
_VIDEO_QUALITY_ARGS = {
    "libx264": ["-crf", "18", "-preset", "medium"],
    "h264_nvenc": ["-rc", "vbr", "-cq", "19", "-b:v", "0"],
    "h264_qsv": ["-global_quality", "20"],
    "h264_amf": ["-rc", "cqp", "-qp_i", "20", "-qp_p", "20", "-qp_b", "20"],
}


def video_encoder_args(encoder: str) -> list[str]:
    """영상 인코더와 그에 맞는 품질 고정 인자를 반환한다.

    `-c:v <encoder>` 뒤에 인코더별 품질 파라미터를 붙인다. 이 품질 지정이
    없으면 하드웨어 인코더가 기본 저비트레이트로 재압축해 원본보다 파일이
    과하게 작아지고 화질이 떨어진다.
    """
    quality = _VIDEO_QUALITY_ARGS.get(encoder, [])
    return ["-c:v", encoder, *quality]


def audio_encoder_args(
    output_ext: str, has_video: bool, source_bitrate: int | None
) -> list[str]:
    """오디오 코덱/비트레이트 인자를 정한다.

    precise 모드는 필터를 거치므로 오디오 재인코딩이 불가피하다. 손실을
    최소화하기 위해:
    - 오디오 전용 + 무손실 가능 컨테이너(wav/flac) → 무손실 코덱.
    - 그 외(영상 파일, mp3/ogg 등 손실 컨테이너) → 소스 비트레이트에 맞춘 AAC.
      소스 비트레이트를 모르면 192k로 폴백.
    """
    ext = output_ext.lower()
    if not has_video and ext in _LOSSLESS_AUDIO_CODECS:
        return ["-c:a", _LOSSLESS_AUDIO_CODECS[ext]]

    if source_bitrate and source_bitrate > 0:
        kbps = max(64, min(round(source_bitrate / 1000), 512))
        bitrate = f"{kbps}k"
    else:
        bitrate = "192k"
    return ["-c:a", "aac", "-b:a", bitrate]


def _segment_args(
    input_path: str,
    seg: Interval,
    seg_path: str,
    has_video: bool,
    encoder: str | None,
    hwaccel: str | None,
) -> list[str]:
    """한 keep 구간을 재인코딩하는 ffmpeg 인자.

    입력 앞의 -ss로 가장 가까운 키프레임까지 빠르게 시크한 뒤 재인코딩하므로
    프레임 정확한 컷이 되고, 매번 소스를 처음부터 디코드하지 않는다(선형 확장).
    오디오는 무손실 PCM으로 담는다 — 손실 코덱(AAC 등)은 세그먼트마다 인코더
    딜레이(priming)가 붙어 수천 조인에서 A/V 싱크가 밀리기 때문. 최종 오디오
    인코딩은 concat 단계에서 이어붙인 스트림 전체에 대해 한 번만 한다.
    """
    args: list[str] = []
    if has_video and hwaccel:
        args += ["-hwaccel", hwaccel]
    args += ["-ss", str(seg.start), "-i", input_path, "-t", str(seg.duration)]
    if has_video:
        args += video_encoder_args(encoder)
    args += ["-c:a", "pcm_s16le", seg_path]
    return args


def process_precise(
    input_path: str,
    output_path: str,
    keep: list[Interval],
    has_video: bool,
    hwaccel: str | None = "auto",
    on_progress: ProgressCallback | None = None,
) -> None:
    """keep 구간을 개별 재인코딩해 concat demuxer로 이어붙인다. 싱크 100% 보장.

    과거엔 모든 구간을 하나의 filter_complex(split→trim→concat)로 처리했으나,
    이는 (세그먼트 수 × 프레임 수)에 비례해 단일 스레드로 급격히 느려져 컷이
    많은 대용량 파일에서 사실상 멈췄다. 구간별 처리는 각 ffmpeg 호출의 필터가
    짧아 이 병목이 없고, 전체 프레임 수에 선형으로 확장된다.

    각 세그먼트는 무손실(비디오 재인코딩 + PCM 오디오)로 temp에 쓰고, 마지막에
    비디오는 그대로 copy하고 오디오만 목표 코덱으로 한 번 인코딩해 합친다.

    디코드 하드웨어 가속:
    - hwaccel="auto"(기본): 가속(NVDEC/QSV/DXVA 등)이 있으면 사용, 없으면
      소프트웨어 디코드. 가속 초기화가 실패하면 소프트웨어로 자동 폴백한다.
    - hwaccel=None: 가속을 끄고 소프트웨어 디코드만 사용.
    - hwaccel="cuda" 등: 특정 방식을 강제.
    영상이 없는(오디오 전용) 작업엔 디코드 가속을 적용하지 않는다.
    """
    encoder = detect_encoder() if has_video else None
    ext = os.path.splitext(output_path)[1]
    seg_ext = ".mkv" if has_video else ".wav"  # 무손실 중간 컨테이너

    hw: str | None = None
    if has_video and hwaccel:
        hw = detect_hwaccel() if hwaccel == "auto" else hwaccel

    total_dur = sum(s.duration for s in keep) or 1.0
    done_dur = 0.0
    with tempfile.TemporaryDirectory() as workdir:
        seg_files: list[str] = []
        for i, seg in enumerate(keep):
            seg_path = os.path.join(workdir, f"seg_{i:05d}{seg_ext}")
            if hw:
                try:
                    run_ffmpeg(_segment_args(
                        input_path, seg, seg_path, has_video, encoder, hw))
                except subprocess.CalledProcessError:
                    # 가속이 목록엔 있으나 드라이버/코덱 문제로 초기화 실패할 수
                    # 있다. 소프트웨어 디코드로 내려가고 이후 구간도 소프트웨어로.
                    hw = None
                    run_ffmpeg(_segment_args(
                        input_path, seg, seg_path, has_video, encoder, None))
            else:
                run_ffmpeg(_segment_args(
                    input_path, seg, seg_path, has_video, encoder, None))
            seg_files.append(seg_path)
            done_dur += seg.duration
            if on_progress:
                on_progress(_SEGMENT_SHARE * done_dur / total_dur)

        list_path = os.path.join(workdir, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for sp in seg_files:
                safe = sp.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        concat = ["-f", "concat", "-safe", "0", "-i", list_path]
        if has_video:
            concat += ["-c:v", "copy"]
        concat += audio_encoder_args(ext, has_video, get_audio_bitrate(input_path))
        concat += [output_path]
        run_ffmpeg(concat)
    if on_progress:
        on_progress(1.0)


def process_copy(
    input_path: str,
    output_path: str,
    keep: list[Interval],
    workdir: str,
    on_progress: ProgressCallback | None = None,
) -> None:
    """스트림 복사(무손실) 모드. 각 keep 구간을 -c copy로 추출 후 concat demuxer로 잇는다.

    -ss를 입력 앞에 두어 가장 가까운 키프레임으로 빠르게 시크(키프레임 스냅)한다.
    """
    total_dur = sum(s.duration for s in keep) or 1.0
    done_dur = 0.0
    seg_files: list[str] = []
    for i, seg in enumerate(keep):
        seg_path = os.path.join(workdir, f"seg_{i:05d}.mkv")
        run_ffmpeg([
            "-ss", str(seg.start), "-to", str(seg.end),
            "-i", input_path, "-c", "copy", seg_path,
        ])
        seg_files.append(seg_path)
        done_dur += seg.duration
        if on_progress:
            on_progress(_SEGMENT_SHARE * done_dur / total_dur)

    list_path = os.path.join(workdir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for sp in seg_files:
            safe = sp.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", output_path,
    ])
    if on_progress:
        on_progress(1.0)
