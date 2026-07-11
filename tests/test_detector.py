from silence_removal.detector import parse_silences
from silence_removal.segments import Interval

SAMPLE = """\
[silencedetect @ 0x1] silence_start: 2.0
[silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 2.0
frame= 100 fps=0.0
[silencedetect @ 0x1] silence_start: 6.5
[silencedetect @ 0x1] silence_end: 9.25 | silence_duration: 2.75
"""


def test_parse_pairs():
    silences = parse_silences(SAMPLE, total_duration=12.0)
    assert silences == [Interval(2.0, 4.0), Interval(6.5, 9.25)]


def test_trailing_silence_without_end_uses_total_duration():
    text = "[silencedetect @ 0x1] silence_start: 8.0\n"
    silences = parse_silences(text, total_duration=10.0)
    assert silences == [Interval(8.0, 10.0)]


def test_no_silence_returns_empty():
    assert parse_silences("frame= 10 fps=0\n", total_duration=5.0) == []
