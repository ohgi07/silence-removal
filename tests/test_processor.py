from silence_removal.processor import (
    audio_encoder_args,
    build_filter_complex,
    video_encoder_args,
)
from silence_removal.segments import Interval


def test_audio_only_wav_is_lossless_pcm():
    assert audio_encoder_args(".wav", has_video=False, source_bitrate=256000) == [
        "-c:a", "pcm_s16le",
    ]


def test_audio_only_flac_is_lossless():
    assert audio_encoder_args(".flac", has_video=False, source_bitrate=None) == [
        "-c:a", "flac",
    ]


def test_audio_matches_source_bitrate():
    # 소스 256kbps → 출력도 256k AAC
    assert audio_encoder_args(".mp4", has_video=True, source_bitrate=256000) == [
        "-c:a", "aac", "-b:a", "256k",
    ]


def test_audio_unknown_bitrate_falls_back_to_192k():
    assert audio_encoder_args(".mp4", has_video=True, source_bitrate=None) == [
        "-c:a", "aac", "-b:a", "192k",
    ]


def test_audio_only_lossy_container_matches_bitrate_not_lossless():
    # mp3는 무손실이 불가능한 컨테이너 → 소스 비트레이트로 AAC 인코딩
    assert audio_encoder_args(".mp3", has_video=False, source_bitrate=128000) == [
        "-c:a", "aac", "-b:a", "128k",
    ]


def test_video_encoder_args_libx264_uses_crf():
    assert video_encoder_args("libx264") == [
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
    ]


def test_video_encoder_args_hw_encoders_include_quality():
    # 하드웨어 인코더도 품질 목표를 지정해야 한다. 지정하지 않으면 기본
    # 저비트레이트로 인코딩되어 원본보다 과하게 압축된다(회귀 방지).
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        args = video_encoder_args(enc)
        assert args[:2] == ["-c:v", enc]
        assert len(args) > 2, f"{enc} must set a quality target, not encoder alone"


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
import subprocess

import pytest

from silence_removal.detector import detect_silences
from silence_removal.ffmpeg_utils import get_duration
from silence_removal.processor import process_precise


def _patch_precise_ffmpeg(monkeypatch, hwaccel, fail_hwaccel=False):
    """process_precise가 실제 ffmpeg를 부르지 않게 하고 호출 인자를 수집한다.

    반환한 리스트에 run_ffmpeg로 넘어간 args가 순서대로 쌓인다.
    """
    calls: list[list[str]] = []

    def fake_run(args):
        calls.append(args)
        if fail_hwaccel and args[:1] == ["-hwaccel"]:
            raise subprocess.CalledProcessError(1, ["ffmpeg", *args], stderr="hw fail")
        return None

    monkeypatch.setattr("silence_removal.processor.run_ffmpeg", fake_run)
    monkeypatch.setattr("silence_removal.processor.detect_hwaccel", lambda: hwaccel)
    monkeypatch.setattr("silence_removal.processor.detect_encoder", lambda: "h264_nvenc")
    monkeypatch.setattr(
        "silence_removal.processor.get_audio_bitrate", lambda path: 128000
    )
    return calls


def test_precise_uses_hwaccel_decode_when_available(monkeypatch, tmp_path):
    from silence_removal.segments import Interval

    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda")
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0)], has_video=True)

    assert len(calls) == 1
    assert calls[0][:2] == ["-hwaccel", "cuda"]


def test_precise_falls_back_to_software_when_hwaccel_init_fails(monkeypatch, tmp_path):
    from silence_removal.segments import Interval

    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda", fail_hwaccel=True)
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0)], has_video=True)

    assert len(calls) == 2
    assert calls[0][:2] == ["-hwaccel", "cuda"]
    assert "-hwaccel" not in calls[1]  # 두 번째 시도는 소프트웨어 디코드


def test_precise_software_decode_when_no_hwaccel(monkeypatch, tmp_path):
    from silence_removal.segments import Interval

    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel=None)
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0)], has_video=True)

    assert len(calls) == 1
    assert "-hwaccel" not in calls[0]


def test_precise_explicit_none_forces_software_even_if_available(monkeypatch, tmp_path):
    from silence_removal.segments import Interval

    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda")
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0)], has_video=True, hwaccel=None)

    assert len(calls) == 1
    assert "-hwaccel" not in calls[0]


def test_precise_audio_only_skips_hwaccel(monkeypatch, tmp_path):
    # 오디오 전용 작업엔 영상 디코드 가속이 의미 없으므로 붙이지 않는다.
    from silence_removal.segments import Interval

    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda")
    process_precise("in.wav", str(tmp_path / "o.wav"),
                    [Interval(0.0, 1.0)], has_video=False)

    assert len(calls) == 1
    assert "-hwaccel" not in calls[0]


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
def test_precise_handles_many_segments_over_cmdline_limit(
    audio_with_silence, tmp_path
):
    # 실데이터(예: 1763 컷)처럼 세그먼트가 많으면 filter_complex 문자열이
    # Windows 명령줄 한도(32,767자)를 넘는다. 이 경우에도 처리돼야 한다.
    from silence_removal.segments import Interval

    keep = [
        Interval(round(i * 0.009, 3), round(i * 0.009 + 0.006, 3))
        for i in range(600)
    ]
    fc, _ = build_filter_complex(keep, has_video=False)
    # 이 그래프가 실제로 명령줄 한도를 초과함을 확인 (수정 전이라면 실행이 실패)
    assert len(fc) > 32767

    out = str(tmp_path / "many.wav")
    process_precise(audio_with_silence, out, keep, has_video=False)

    import os
    assert os.path.exists(out)
    assert get_duration(out) > 0


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
