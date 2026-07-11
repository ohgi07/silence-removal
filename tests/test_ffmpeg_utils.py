import pytest

from silence_removal.ffmpeg_utils import (
    FFmpegNotFound,
    ensure_ffmpeg,
    pick_hw_encoder,
)


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
