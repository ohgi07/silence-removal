"""ffmpeg/ffprobe 호출 래퍼와 환경 감지."""
from __future__ import annotations

import shutil
import subprocess


class FFmpegNotFound(Exception):
    """ffmpeg 또는 ffprobe를 PATH에서 찾을 수 없을 때."""


# 선호 순서: NVIDIA → Intel QSV → AMD → 소프트웨어
_HW_PREFERENCE = ["h264_nvenc", "h264_qsv", "h264_amf"]


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
