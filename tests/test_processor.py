from silence_removal.processor import build_filter_complex
from silence_removal.segments import Interval


def test_filter_complex_audio_only():
    keep = [Interval(0.0, 2.0), Interval(4.0, 6.0)]
    fc, out_map = build_filter_complex(keep, has_video=False)
    assert "atrim=start=0.0:end=2.0" in fc
    assert "atrim=start=4.0:end=6.0" in fc
    assert "concat=n=2:v=0:a=1" in fc
    assert out_map == ["-map", "[outa]"]


def test_filter_complex_with_video():
    keep = [Interval(0.0, 2.0), Interval(4.0, 6.0)]
    fc, out_map = build_filter_complex(keep, has_video=True)
    assert "trim=start=0.0:end=2.0" in fc
    assert "atrim=start=0.0:end=2.0" in fc
    assert "concat=n=2:v=1:a=1" in fc
    assert out_map == ["-map", "[outv]", "-map", "[outa]"]


import shutil
import pytest

from silence_removal.detector import detect_silences
from silence_removal.ffmpeg_utils import get_duration
from silence_removal.processor import process_precise


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 필요")
def test_precise_audio_removes_silence(audio_with_silence, tmp_path):
    silences, total = detect_silences(
        audio_with_silence, threshold_db=-30, min_silence=0.5
    )
    from silence_removal.segments import compute_keep_segments
    keep = compute_keep_segments(silences, total, keep_silence=0.3)

    out = str(tmp_path / "out.wav")
    process_precise(audio_with_silence, out, keep, has_video=False)

    # 원본 6초, 무음 2초 중 0.3초만 남김 → 약 4.3초
    result_dur = get_duration(out)
    assert 4.0 < result_dur < 4.6


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 필요")
def test_precise_video_removes_silence_and_keeps_streams(
    video_with_silence, tmp_path
):
    from silence_removal.ffmpeg_utils import has_audio, has_video
    from silence_removal.segments import compute_keep_segments

    silences, total = detect_silences(
        video_with_silence, threshold_db=-30, min_silence=0.5
    )
    keep = compute_keep_segments(silences, total, keep_silence=0.3)

    out = str(tmp_path / "out.mp4")
    process_precise(video_with_silence, out, keep, has_video=True)

    assert 4.0 < get_duration(out) < 4.6
    assert has_video(out) is True
    assert has_audio(out) is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 필요")
def test_copy_video_produces_playable_output(video_with_silence, tmp_path):
    from silence_removal.ffmpeg_utils import has_audio, has_video
    from silence_removal.processor import process_copy
    from silence_removal.segments import compute_keep_segments

    silences, total = detect_silences(
        video_with_silence, threshold_db=-30, min_silence=0.5
    )
    keep = compute_keep_segments(silences, total, keep_silence=0.3)

    workdir = tmp_path / "work"
    workdir.mkdir()
    out = str(tmp_path / "out_copy.mkv")
    process_copy(video_with_silence, out, keep, str(workdir))

    # copy는 키프레임 스냅이라 정확한 길이는 다를 수 있으나, 재생 가능한 A/V가 있어야 함
    assert has_video(out) is True
    assert has_audio(out) is True
    assert get_duration(out) > 0
