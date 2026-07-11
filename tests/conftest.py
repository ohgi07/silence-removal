import subprocess

import pytest


def _run(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-y", *args],
                   capture_output=True, text=True, check=True)


@pytest.fixture
def audio_with_silence(tmp_path):
    """6초 톤, 단 2~4초 구간만 무음인 wav 파일."""
    out = tmp_path / "audio.wav"
    _run([
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=6:sample_rate=44100",
        "-af", "volume=enable='between(t,2,4)':volume=0",
        str(out),
    ])
    return str(out)


@pytest.fixture
def video_with_silence(tmp_path):
    """6초 영상, 오디오는 2~4초 구간만 무음인 mp4 파일."""
    out = tmp_path / "video.mp4"
    _run([
        "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6:sample_rate=44100",
        "-af", "volume=enable='between(t,2,4)':volume=0",
        "-shortest", "-pix_fmt", "yuv420p", str(out),
    ])
    return str(out)
