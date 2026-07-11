"""ffmpeg silencedetect를 실행하고 결과를 파싱해 무음 구간을 얻는다."""
from __future__ import annotations

import re

from .ffmpeg_utils import get_duration, run_ffmpeg
from .segments import Interval

_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def parse_silences(stderr_text: str, total_duration: float) -> list[Interval]:
    """silencedetect stderr 출력을 무음 Interval 목록으로 파싱.

    마지막 무음에 silence_end가 없으면(파일이 무음으로 끝남) total_duration으로 닫는다.
    """
    starts: list[float] = []
    ends: list[float] = []
    for line in stderr_text.splitlines():
        m = _START_RE.search(line)
        if m:
            starts.append(float(m.group(1)))
        m = _END_RE.search(line)
        if m:
            ends.append(float(m.group(1)))

    silences: list[Interval] = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else total_duration
        # 음수 클램프 및 경계 보정
        start = max(0.0, start)
        end = min(total_duration, end)
        if end > start:
            silences.append(Interval(start, end))
    return silences


def detect_silences(
    path: str, threshold_db: float, min_silence: float
) -> tuple[list[Interval], float]:
    """파일에서 무음 구간과 전체 길이를 감지한다.

    오디오만 디코딩(-vn)하여 대용량 영상에서도 빠르다.
    반환: (무음 Interval 목록, 전체 길이 초).
    """
    total = get_duration(path)
    args = [
        "-i", path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence}",
        "-vn", "-f", "null", "-",
    ]
    result = run_ffmpeg(args)
    silences = parse_silences(result.stderr, total)
    return silences, total
