"""ffmpeg/ffprobe 호출 래퍼와 환경 감지."""
from __future__ import annotations

import shutil
import subprocess


class FFmpegNotFound(Exception):
    """ffmpeg 또는 ffprobe를 PATH에서 찾을 수 없을 때."""


# 선호 순서: NVIDIA → Intel QSV → AMD → 소프트웨어
_HW_PREFERENCE = ["h264_nvenc", "h264_qsv", "h264_amf"]

# 디코드용 하드웨어 가속 선호 순서.
#   cuda(NVIDIA)·qsv(Intel)는 벤더 전용, d3d11va·dxva2는 Windows 범용(AMD 포함),
#   vaapi는 Linux. -hwaccel은 코덱 미지원 시 소프트웨어로 자동 폴백하므로 안전하다.
_HWACCEL_PREFERENCE = ["cuda", "qsv", "d3d11va", "dxva2", "vaapi"]


def ensure_ffmpeg() -> None:
    """ffmpeg와 ffprobe가 설치돼 있는지 확인. 없으면 FFmpegNotFound."""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegNotFound(
                f"'{tool}'를 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 추가하세요.\n"
                "Windows: winget install Gyan.FFmpeg  또는  https://ffmpeg.org"
            )


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """ffmpeg 실행. stdout/stderr 캡처. 실패 시 CalledProcessError."""
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _ffprobe(args: list[str]) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_duration(path: str) -> float:
    """미디어 전체 길이(초)."""
    out = _ffprobe(
        ["-show_entries", "format=duration", "-of", "default=nk=1:nw=1", path]
    )
    return float(out)


def get_audio_bitrate(path: str) -> int | None:
    """첫 오디오 스트림의 비트레이트(bps). 알 수 없으면 None.

    일부 컨테이너는 스트림 비트레이트를 'N/A'로 보고하는데, 그 경우 None.
    """
    out = _ffprobe(
        ["-select_streams", "a:0", "-show_entries", "stream=bit_rate",
         "-of", "default=nk=1:nw=1", path]
    )
    try:
        return int(out)
    except (ValueError, TypeError):
        return None


def has_audio(path: str) -> bool:
    """오디오 스트림이 하나라도 있는지."""
    out = _ffprobe(
        ["-select_streams", "a", "-show_entries", "stream=index",
         "-of", "default=nk=1:nw=1", path]
    )
    return bool(out)


def has_video(path: str) -> bool:
    """영상 스트림이 하나라도 있는지 (썸네일 아닌 실제 영상)."""
    out = _ffprobe(
        ["-select_streams", "v", "-show_entries", "stream=codec_type",
         "-of", "default=nk=1:nw=1", path]
    )
    return "video" in out


def pick_hw_encoder(encoders_output: str) -> str:
    """`ffmpeg -encoders` 출력에서 사용할 H.264 인코더를 고른다.

    선호 하드웨어 인코더가 있으면 그것을, 없으면 libx264.
    """
    for enc in _HW_PREFERENCE:
        if enc in encoders_output:
            return enc
    return "libx264"


def detect_encoder() -> str:
    """현재 시스템에서 사용할 H.264 인코더 이름."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=True,
    )
    return pick_hw_encoder(result.stdout)


def pick_hwaccel(hwaccels_output: str) -> str | None:
    """`ffmpeg -hwaccels` 출력에서 디코드에 쓸 하드웨어 가속 방식을 고른다.

    각 방식은 한 줄에 하나씩 나온다. 선호 순서상 처음 발견되는 것을,
    아무 가속도 없으면 None(소프트웨어 디코드)을 반환한다.
    """
    available = {
        line.strip() for line in hwaccels_output.splitlines() if line.strip()
    }
    for hw in _HWACCEL_PREFERENCE:
        if hw in available:
            return hw
    return None


def detect_hwaccel() -> str | None:
    """현재 시스템에서 디코드에 쓸 하드웨어 가속 방식. 없으면 None."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-hwaccels"],
        capture_output=True,
        text=True,
        check=True,
    )
    return pick_hwaccel(result.stdout)
