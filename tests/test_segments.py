from silence_removal.segments import Interval, compute_keep_segments


def approx(segs):
    return [(round(s.start, 3), round(s.end, 3)) for s in segs]


def test_no_silence_keeps_whole():
    keep = compute_keep_segments([], total_duration=10.0, keep_silence=0.3)
    assert approx(keep) == [(0.0, 10.0)]


def test_short_silence_below_keep_is_untouched():
    # 무음 길이 0.2 < keep_silence 0.3 → 그대로 유지, 통짜 한 구간
    silences = [Interval(4.0, 4.2)]
    keep = compute_keep_segments(silences, total_duration=10.0, keep_silence=0.3)
    assert approx(keep) == [(0.0, 10.0)]


def test_long_middle_silence_is_trimmed_half_each_side():
    # 무음 4.0~7.0 (3초). keep_silence 0.3 → 가운데 제거, 앞뒤 0.15씩 남김.
    # 제거 구간 = 4.15 ~ 6.85. keep = [0~4.15], [6.85~10]
    silences = [Interval(4.0, 7.0)]
    keep = compute_keep_segments(silences, total_duration=10.0, keep_silence=0.3)
    assert approx(keep) == [(0.0, 4.15), (6.85, 10.0)]


def test_multiple_silences():
    silences = [Interval(2.0, 4.0), Interval(6.0, 9.0)]
    keep = compute_keep_segments(silences, total_duration=12.0, keep_silence=0.4)
    # 제거: [2.2~3.8], [6.2~8.8]
    assert approx(keep) == [(0.0, 2.2), (3.8, 6.2), (8.8, 12.0)]


def test_leading_silence():
    # 파일 맨 앞 무음 0~3. 제거 0.15~2.85. keep = [0~0.15], [2.85~10]
    silences = [Interval(0.0, 3.0)]
    keep = compute_keep_segments(silences, total_duration=10.0, keep_silence=0.3)
    assert approx(keep) == [(0.0, 0.15), (2.85, 10.0)]


def test_silence_equal_to_keep_is_untouched():
    silences = [Interval(4.0, 4.3)]
    keep = compute_keep_segments(silences, total_duration=10.0, keep_silence=0.3)
    assert approx(keep) == [(0.0, 10.0)]
