import pytest

from silence_removal.ffmpeg_utils import (
    FFmpegNotFound,
    ensure_ffmpeg,
    pick_hw_encoder,
    pick_hwaccel,
)


# `ffmpeg -hwaccels` 출력 형식: 헤더 한 줄 + 방식별 한 줄씩.
_HWACCELS_HEADER = "Hardware acceleration methods:\n"


def test_pick_hwaccel_prefers_cuda():
    out = _HWACCELS_HEADER + "cuda\nqsv\nd3d11va\ndxva2\n"
    assert pick_hwaccel(out) == "cuda"


def test_pick_hwaccel_qsv_when_no_cuda():
    out = _HWACCELS_HEADER + "qsv\nd3d11va\ndxva2\n"
    assert pick_hwaccel(out) == "qsv"


def test_pick_hwaccel_d3d11va_when_no_cuda_or_qsv():
    # Intel/NVIDIA 전용 가속이 없어도 Windows 범용 가속으로 디코드 가속 가능.
    out = _HWACCELS_HEADER + "d3d11va\ndxva2\n"
    assert pick_hwaccel(out) == "d3d11va"


def test_pick_hwaccel_none_when_software_only():
    # 어떤 하드웨어 디코드 가속도 없는 시스템 → None(소프트웨어 디코드).
    assert pick_hwaccel(_HWACCELS_HEADER) is None
    assert pick_hwaccel("Hardware acceleration methods:\n\n") is None


def test_pick_hwaccel_ignores_substring_false_positives():
    # 헤더 문구에 'cuda' 등이 없으므로 헤더만 있으면 매칭되면 안 된다.
    assert pick_hwaccel("Hardware acceleration methods:\n") is None


def test_pick_hw_encoder_prefers_nvenc():
    encoders_output = "V..... h264_nvenc\nV..... h264_qsv\n"
    assert pick_hw_encoder(encoders_output) == "h264_nvenc"


def test_pick_hw_encoder_qsv_when_no_nvenc():
    encoders_output = "V..... h264_qsv\nV..... h264_amf\n"
    assert pick_hw_encoder(encoders_output) == "h264_qsv"


def test_pick_hw_encoder_none_falls_back_to_libx264():
    assert pick_hw_encoder("V..... mpeg4\n") == "libx264"


def test_ensure_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr("silence_removal.ffmpeg_utils.shutil.which", lambda name: None)
    with pytest.raises(FFmpegNotFound):
        ensure_ffmpeg()
