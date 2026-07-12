from silence_removal.processor import (
    audio_encoder_args,
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


def test_process_precise_reports_progress(audio_with_silence, tmp_path):
    from silence_removal.detector import detect_silences
    from silence_removal.processor import process_precise
    from silence_removal.segments import compute_keep_segments

    silences, total = detect_silences(audio_with_silence, threshold_db=-30, min_silence=0.5)
    keep = compute_keep_segments(silences, total, keep_silence=0.3)

    fracs: list[float] = []
    out = str(tmp_path / "out.wav")
    process_precise(audio_with_silence, out, keep, has_video=False, on_progress=fracs.append)

    assert fracs, "진행 콜백이 최소 한 번은 호출되어야 한다"
    assert fracs == sorted(fracs), "진행률은 단조 증가해야 한다"
    assert all(0.0 <= f <= 1.0 for f in fracs)
    assert fracs[-1] == 1.0, "마지막 진행률은 100%여야 한다"


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


import shutil
import subprocess

import pytest

from silence_removal.detector import detect_silences
from silence_removal.ffmpeg_utils import get_duration
from silence_removal.processor import process_precise


def _patch_precise_ffmpeg(monkeypatch, hwaccel, fail_hwaccel=False):
    """process_precise가 실제 ffmpeg를 부르지 않게 하고 호출 인자를 수집한다.

    process_precise는 keep 구간마다 run_ffmpeg를 한 번씩 호출한 뒤 마지막에
    concat을 호출한다. 반환 리스트에 각 호출 args가 순서대로 쌓인다.
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


def _seg_calls(calls):
    """세그먼트 인코딩 호출만(마지막 concat 호출 제외)."""
    return [c for c in calls if c[:1] != ["-f"]]


def _concat_call(calls):
    return next(c for c in calls if c[:1] == ["-f"])


def test_precise_uses_hwaccel_decode_on_each_segment(monkeypatch, tmp_path):
    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda")
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0), Interval(2.0, 3.0)], has_video=True)

    seg = _seg_calls(calls)
    assert len(seg) == 2
    for c in seg:
        assert c[:2] == ["-hwaccel", "cuda"]
    # 세그먼트 오디오는 무손실 PCM으로 담는다(조인 priming 방지).
    assert "pcm_s16le" in seg[0]
    # concat 단계는 디코드 가속 불필요, 비디오는 copy.
    assert "-hwaccel" not in _concat_call(calls)
    assert ["-c:v", "copy"] == _concat_call(calls)[6:8]


def test_precise_falls_back_to_software_when_hwaccel_init_fails(monkeypatch, tmp_path):
    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda", fail_hwaccel=True)
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0), Interval(2.0, 3.0)], has_video=True)

    seg = _seg_calls(calls)
    # 첫 구간: 가속 시도(실패) → 소프트웨어 재시도. 이후 구간은 바로 소프트웨어.
    assert seg[0][:2] == ["-hwaccel", "cuda"]      # 실패한 시도
    assert "-hwaccel" not in seg[1]                # 같은 구간 소프트웨어 재시도
    assert "-hwaccel" not in seg[2]                # 다음 구간도 소프트웨어


def test_precise_software_decode_when_no_hwaccel(monkeypatch, tmp_path):
    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel=None)
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0)], has_video=True)

    for c in _seg_calls(calls):
        assert "-hwaccel" not in c


def test_precise_explicit_none_forces_software_even_if_available(monkeypatch, tmp_path):
    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda")
    process_precise("in.mp4", str(tmp_path / "o.mp4"),
                    [Interval(0.0, 1.0)], has_video=True, hwaccel=None)

    for c in _seg_calls(calls):
        assert "-hwaccel" not in c


def test_precise_audio_only_skips_hwaccel(monkeypatch, tmp_path):
    # 오디오 전용 작업엔 영상 디코드 가속이 의미 없으므로 붙이지 않는다.
    calls = _patch_precise_ffmpeg(monkeypatch, hwaccel="cuda")
    process_precise("in.wav", str(tmp_path / "o.wav"),
                    [Interval(0.0, 1.0)], has_video=False)

    for c in _seg_calls(calls):
        assert "-hwaccel" not in c
    # 오디오 전용은 concat에 비디오 copy가 없어야 한다.
    assert "-c:v" not in _concat_call(calls)


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
def test_precise_handles_many_segments(audio_with_silence, tmp_path):
    # 컷이 많은 실데이터(수백~수천 세그먼트) 회귀 방지. 구간별 처리는 각 호출이
    # 세그먼트 하나라 필터그래프가 짧고, 세그먼트 수에 선형으로 확장된다(과거
    # 단일 filter_complex 방식은 여기서 급격히 느려져 대용량 파일에서 멈췄다).
    from silence_removal.segments import Interval

    # 6초 클립을 40개의 0.1초 구간으로 → 이어붙이면 약 4초.
    keep = [
        Interval(round(i * 0.15, 3), round(i * 0.15 + 0.1, 3))
        for i in range(40)
    ]
    out = str(tmp_path / "many.wav")
    process_precise(audio_with_silence, out, keep, has_video=False)

    import os
    assert os.path.exists(out)
    # 이어붙인 길이가 keep 총합(4.0초)에 근접해야 한다(구간 누락/중복 없음).
    assert abs(get_duration(out) - 4.0) < 0.3


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
