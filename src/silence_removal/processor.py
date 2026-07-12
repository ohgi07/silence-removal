"""keep 구간대로 잘라 이어붙여 출력 파일을 만든다."""
from __future__ import annotations

import os
import subprocess
import tempfile

from .ffmpeg_utils import (
    detect_encoder,
    detect_hwaccel,
    get_audio_bitrate,
    run_ffmpeg,
)
from .segments import Interval

# 무손실 출력이 가능한 오디오 전용 컨테이너 → 무손실 코덱.
_LOSSLESS_AUDIO_CODECS = {".wav": "pcm_s16le", ".flac": "flac"}


def build_filter_complex(
    keep: list[Interval], has_video: bool
) -> tuple[str, list[str]]:
    """precise 모드용 filter_complex 문자열과 -map 인자를 만든다.

    각 keep 구간을 trim/atrim으로 자르고 setpts로 타임스탬프를 0부터 다시 흘린 뒤
    concat 필터로 이어붙인다. 이 재흐름이 A/V 싱크를 보장한다.
    """
    parts: list[str] = []
    concat_inputs: list[str] = []
    for i, seg in enumerate(keep):
        if has_video:
            parts.append(
                f"[0:v]trim=start={seg.start}:end={seg.end},"
                f"setpts=PTS-STARTPTS[v{i}]"
            )
            concat_inputs.append(f"[v{i}]")
        parts.append(
            f"[0:a]atrim=start={seg.start}:end={seg.end},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[a{i}]")

    n = len(keep)
    if has_video:
        concat = (
            "".join(concat_inputs)
            + f"concat=n={n}:v=1:a=1[outv][outa]"
        )
        out_map = ["-map", "[outv]", "-map", "[outa]"]
    else:
        concat = (
            "".join(concat_inputs)
            + f"concat=n={n}:v=0:a=1[outa]"
        )
        out_map = ["-map", "[outa]"]

    filter_complex = ";".join(parts) + ";" + concat
    return filter_complex, out_map


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


def process_precise(
    input_path: str,
    output_path: str,
    keep: list[Interval],
    has_video: bool,
    hwaccel: str | None = "auto",
) -> None:
    """단일 패스 재인코딩으로 잘라 이어붙인다. 싱크 100% 보장.

    필터 그래프는 -filter_complex_script로 파일에 담아 넘긴다. 세그먼트가 많으면
    (예: 수백~수천 컷) 그래프 문자열이 Windows 명령줄 한도(32,767자)를 넘기 때문.

    디코드 하드웨어 가속:
    - hwaccel="auto"(기본): 시스템에 가속(NVDEC/QSV/DXVA 등)이 있으면 사용,
      없으면 소프트웨어 디코드. 가속 초기화가 실패해도 소프트웨어로 자동 재시도한다.
    - hwaccel=None: 가속을 끄고 소프트웨어 디코드만 사용.
    - hwaccel="cuda" 등: 특정 방식을 강제.
    영상이 없는(오디오 전용) 작업엔 디코드 가속을 적용하지 않는다.
    """
    fc, out_map = build_filter_complex(keep, has_video)
    fd, script_path = tempfile.mkstemp(suffix=".ffscript", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(fc)
        args = ["-i", input_path, "-filter_complex_script", script_path, *out_map]
        if has_video:
            args += video_encoder_args(detect_encoder())
        ext = os.path.splitext(output_path)[1]
        args += audio_encoder_args(ext, has_video, get_audio_bitrate(input_path))
        args += [output_path]

        hw = None
        if has_video and hwaccel:
            hw = detect_hwaccel() if hwaccel == "auto" else hwaccel

        if hw:
            try:
                run_ffmpeg(["-hwaccel", hw, *args])
                return
            except subprocess.CalledProcessError:
                # 가속이 목록엔 있으나 드라이버/코덱 문제로 초기화 실패할 수 있다.
                # 이 경우 소프트웨어 디코드로 폴백해 처리를 이어간다.
                pass
        run_ffmpeg(args)
    finally:
        os.unlink(script_path)


def process_copy(
    input_path: str, output_path: str, keep: list[Interval], workdir: str
) -> None:
    """스트림 복사(무손실) 모드. 각 keep 구간을 -c copy로 추출 후 concat demuxer로 잇는다.

    -ss를 입력 앞에 두어 가장 가까운 키프레임으로 빠르게 시크(키프레임 스냅)한다.
    """
    seg_files: list[str] = []
    for i, seg in enumerate(keep):
        seg_path = os.path.join(workdir, f"seg_{i:05d}.mkv")
        run_ffmpeg([
            "-ss", str(seg.start), "-to", str(seg.end),
            "-i", input_path, "-c", "copy", seg_path,
        ])
        seg_files.append(seg_path)

    list_path = os.path.join(workdir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for sp in seg_files:
            safe = sp.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", output_path,
    ])
