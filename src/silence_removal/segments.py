"""무음 목록으로부터 남길(keep) 구간을 계산하는 순수 함수 모듈.

ffmpeg에 의존하지 않는다. 프로그램의 '두뇌'.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    """시간 구간 (초 단위). start < end 를 전제로 한다."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _compute_removed_intervals(
    silences: list[Interval], keep_silence: float
) -> list[Interval]:
    """각 무음에서 실제로 잘라낼 구간을 계산.

    무음 길이가 keep_silence 이하면 건드리지 않는다.
    더 길면 가운데를 잘라내고 앞뒤로 keep_silence/2 씩 남긴다.
    """
    half = keep_silence / 2
    removed: list[Interval] = []
    for s in silences:
        if s.duration > keep_silence:
            removed.append(Interval(s.start + half, s.end - half))
    return removed


def compute_keep_segments(
    silences: list[Interval], total_duration: float, keep_silence: float
) -> list[Interval]:
    """남길 구간 목록을 반환한다 (잘라낼 구간의 여집합).

    silences: 정렬되고 서로 겹치지 않는 무음 구간 목록.
    total_duration: 전체 길이(초).
    keep_silence: 잘라낸 무음에 남길 총 길이(초), 앞뒤 절반씩.
    """
    removed = _compute_removed_intervals(silences, keep_silence)
    keep: list[Interval] = []
    cursor = 0.0
    for r in removed:
        if r.start > cursor:
            keep.append(Interval(cursor, r.start))
        cursor = max(cursor, r.end)
    if cursor < total_duration:
        keep.append(Interval(cursor, total_duration))
    return keep
