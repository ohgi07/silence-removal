# 무음 구간 제거 프로그램 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 녹화·녹음 파일(영상+오디오)에서 무음 구간을 짧게 줄여 정리하는 CLI 도구를 만든다.

**Architecture:** Python이 오케스트레이션하고 ffmpeg가 미디어 작업을 전담한다. 무음 감지(`detector`) → 순수 함수 두뇌(`segments`)가 keep 구간 계산 → 잘라 이어붙이기(`processor`). 영상 기본은 재인코딩(`precise`, 싱크 100% 보장), 옵션으로 무손실 스트림복사(`copy`). 결과는 사람용 로그(stderr) 또는 에이전트용 JSON(stdout)으로 출력.

**Tech Stack:** Python 3.10+, ffmpeg/ffprobe(외부 바이너리), pytest. 서드파티 파이썬 의존성 없음(표준 라이브러리 `subprocess`, `argparse`, `shutil`, `json`, `re`, `dataclasses`).

---

## 사전 준비

- 시스템에 `ffmpeg`와 `ffprobe`가 PATH에 있어야 한다 (통합 테스트에 필요). 확인: `ffmpeg -version`, `ffprobe -version`.
- Windows에서 없으면 `winget install Gyan.FFmpeg` 또는 https://ffmpeg.org 에서 설치.

---

### Task 1: 프로젝트 스캐폴드

**Files:**
- Create: `pyproject.toml`
- Create: `src/silence_removal/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: `pyproject.toml` 작성**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "silence-removal"
version = "0.1.0"
description = "녹화·녹음 파일의 무음 구간을 짧게 줄여 정리하는 CLI 도구"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
silence-removal = "silence_removal.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 패키지/테스트 빈 파일 생성**

`src/silence_removal/__init__.py`:
```python
"""무음 구간 제거 CLI 도구."""
__version__ = "0.1.0"
```

`tests/__init__.py`: (빈 파일)

- [ ] **Step 3: `.gitignore` 작성**

```
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
build/
dist/
/tmp_test_media/
```

- [ ] **Step 4: 개발 설치 및 확인**

Run: `pip install -e ".[dev]"`
그다음: `pytest -q`
Expected: `no tests ran` (아직 테스트 없음, 에러 없이 종료)

- [ ] **Step 5: git 초기화 및 커밋**

```bash
git init
git add .
git commit -m "chore: scaffold silence-removal project"
```

---

### Task 2: 두뇌 — keep 구간 계산 (`segments.py`)

프로그램의 핵심. 순수 함수라 ffmpeg 없이 완전 테스트 가능. 먼저 작성한다.

**모델**: 무음(`Interval`) 목록을 받아, `keep_silence`보다 긴 무음은 가운데를 잘라내고 앞뒤로 `keep_silence/2`씩만 남긴다. 최종 "남길(keep)" 구간 목록을 반환한다.

**Files:**
- Create: `src/silence_removal/segments.py`
- Test: `tests/test_segments.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_segments.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_segments.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 `ImportError: cannot import name 'Interval'`

- [ ] **Step 3: 최소 구현 작성**

`src/silence_removal/segments.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_segments.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/silence_removal/segments.py tests/test_segments.py
git commit -m "feat: add pure keep-segment computation (brain)"
```

---

### Task 3: 무음 감지 파서 (`detector.py`)

ffmpeg `silencedetect`의 stderr 출력을 파싱하는 부분은 순수 함수라 TDD 가능. 실제 ffmpeg 실행은 그 위에 얹는다.

**Files:**
- Create: `src/silence_removal/detector.py`
- Test: `tests/test_detector.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_detector.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_detector.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_silences'`

- [ ] **Step 3: 파서 구현 작성**

`src/silence_removal/detector.py` (파서 부분만 우선):
```python
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
```

> 참고: `detect_silences`는 Task 4의 `get_duration`, `run_ffmpeg`에 의존한다. 이 테스트(`parse_silences`)는 순수 함수만 검증하므로 Task 4 없이도 통과한다. import가 문제되면 Task 4를 먼저 수행하거나, 이 단계에서 `ffmpeg_utils.py`에 두 함수의 최소 스텁을 만든 뒤 Task 4에서 완성한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_detector.py -v`
Expected: PASS (3 passed)
(만약 `ffmpeg_utils` import 에러가 나면 Task 4를 먼저 진행)

- [ ] **Step 5: 커밋**

```bash
git add src/silence_removal/detector.py tests/test_detector.py
git commit -m "feat: parse silencedetect output into intervals"
```

---

### Task 4: ffmpeg 유틸리티 (`ffmpeg_utils.py`)

**Files:**
- Create: `src/silence_removal/ffmpeg_utils.py`
- Test: `tests/test_ffmpeg_utils.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ffmpeg_utils.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_ffmpeg_utils.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 구현 작성**

`src/silence_removal/ffmpeg_utils.py`:
```python
"""ffmpeg/ffprobe 호출 래퍼와 환경 감지."""
from __future__ import annotations

import shutil
import subprocess


class FFmpegNotFound(Exception):
    """ffmpeg 또는 ffprobe를 PATH에서 찾을 수 없을 때."""


# 선호 순서: NVIDIA → Intel QSV → AMD → 소프트웨어
_HW_PREFERENCE = ["h264_nvenc", "h264_qsv", "h264_amf"]


def ensure_ffmpeg() -> None:
    """ffmpeg와 ffprobe가 설치돼 있는지 확인. 없으면 FFmpegNotFound."""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegNotFound(
                f"'{tool}'를 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 추가하세요.\n"
                "Windows: winget install Gyan.FFmpeg  또는  https://ffmpeg.org"
            )


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """ffmpeg 실행. stdout/stderr 캡처. 실패 시 CalledProcessError."""
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _ffprobe(args: list[str]) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_duration(path: str) -> float:
    """미디어 전체 길이(초)."""
    out = _ffprobe(
        ["-show_entries", "format=duration", "-of", "default=nk=1:nw=1", path]
    )
    return float(out)


def has_audio(path: str) -> bool:
    """오디오 스트림이 하나라도 있는지."""
    out = _ffprobe(
        ["-select_streams", "a", "-show_entries", "stream=index",
         "-of", "default=nk=1:nw=1", path]
    )
    return bool(out)


def has_video(path: str) -> bool:
    """영상 스트림이 하나라도 있는지 (썸네일 아닌 실제 영상)."""
    out = _ffprobe(
        ["-select_streams", "v", "-show_entries", "stream=codec_type",
         "-of", "default=nk=1:nw=1", path]
    )
    return "video" in out


def pick_hw_encoder(encoders_output: str) -> str:
    """`ffmpeg -encoders` 출력에서 사용할 H.264 인코더를 고른다.

    선호 하드웨어 인코더가 있으면 그것을, 없으면 libx264.
    """
    for enc in _HW_PREFERENCE:
        if enc in encoders_output:
            return enc
    return "libx264"


def detect_encoder() -> str:
    """현재 시스템에서 사용할 H.264 인코더 이름."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=True,
    )
    return pick_hw_encoder(result.stdout)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_ffmpeg_utils.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: detector 테스트도 여전히 통과하는지 확인**

Run: `pytest tests/test_detector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/silence_removal/ffmpeg_utils.py tests/test_ffmpeg_utils.py
git commit -m "feat: add ffmpeg/ffprobe wrappers and hw encoder detection"
```

---

### Task 5: 처리기 — filter_complex 빌더 + 오디오 통합 (`processor.py`)

`precise` 모드는 ffmpeg `filter_complex`의 trim/atrim + concat으로 단일 패스 재인코딩한다. 필터 문자열 빌더는 순수 함수라 단위 테스트하고, 실제 처리는 합성 샘플로 통합 테스트한다.

**Files:**
- Create: `src/silence_removal/processor.py`
- Test: `tests/test_processor.py`
- Create: `tests/conftest.py` (합성 미디어 픽스처)

- [ ] **Step 1: 필터 빌더 실패 테스트 작성**

`tests/test_processor.py` (우선 순수 함수만):
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_processor.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_filter_complex'`

- [ ] **Step 3: 처리기 구현 작성**

`src/silence_removal/processor.py`:
```python
"""keep 구간대로 잘라 이어붙여 출력 파일을 만든다."""
from __future__ import annotations

import os
import subprocess

from .ffmpeg_utils import detect_encoder, has_video as probe_has_video, run_ffmpeg
from .segments import Interval


def build_filter_complex(
    keep: list[Interval], has_video: bool
) -> tuple[str, list[str]]:
    """precise 모드용 filter_complex 문자열과 -map 인자를 만든다.

    각 keep 구간을 trim/atrim으로 자르고 setpts로 타임스탬프를 0부터 다시 흘린 뒤
    concat 필터로 이어붙인다. 이 재흐름이 A/V 싱크를 보장한다.
    """
    parts: list[str] = []
    concat_inputs: list[str] = []
    for i, seg in enumerate(keep):
        if has_video:
            parts.append(
                f"[0:v]trim=start={seg.start}:end={seg.end},"
                f"setpts=PTS-STARTPTS[v{i}]"
            )
            concat_inputs.append(f"[v{i}]")
        parts.append(
            f"[0:a]atrim=start={seg.start}:end={seg.end},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[a{i}]")

    n = len(keep)
    if has_video:
        concat = (
            "".join(concat_inputs)
            + f"concat=n={n}:v=1:a=1[outv][outa]"
        )
        out_map = ["-map", "[outv]", "-map", "[outa]"]
    else:
        concat = (
            "".join(concat_inputs)
            + f"concat=n={n}:v=0:a=1[outa]"
        )
        out_map = ["-map", "[outa]"]

    filter_complex = ";".join(parts) + ";" + concat
    return filter_complex, out_map


def process_precise(
    input_path: str, output_path: str, keep: list[Interval], has_video: bool
) -> None:
    """단일 패스 재인코딩으로 잘라 이어붙인다. 싱크 100% 보장."""
    fc, out_map = build_filter_complex(keep, has_video)
    args = ["-i", input_path, "-filter_complex", fc, *out_map]
    if has_video:
        encoder = detect_encoder()
        args += ["-c:v", encoder]
        if encoder == "libx264":
            args += ["-crf", "18", "-preset", "medium"]
    args += ["-c:a", "aac", "-b:a", "192k", output_path]
    run_ffmpeg(args)


def process_copy(
    input_path: str, output_path: str, keep: list[Interval], workdir: str
) -> None:
    """스트림 복사(무손실) 모드. 각 keep 구간을 -c copy로 추출 후 concat demuxer로 잇는다.

    -ss를 입력 앞에 두어 가장 가까운 키프레임으로 빠르게 시크(키프레임 스냅)한다.
    """
    seg_files: list[str] = []
    for i, seg in enumerate(keep):
        seg_path = os.path.join(workdir, f"seg_{i:05d}.mkv")
        run_ffmpeg([
            "-ss", str(seg.start), "-to", str(seg.end),
            "-i", input_path, "-c", "copy", seg_path,
        ])
        seg_files.append(seg_path)

    list_path = os.path.join(workdir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for sp in seg_files:
            safe = sp.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", output_path,
    ])
```

- [ ] **Step 4: 필터 빌더 테스트 통과 확인**

Run: `pytest tests/test_processor.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 합성 미디어 픽스처 작성**

`tests/conftest.py`:
```python
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
```

- [ ] **Step 6: 오디오 통합 테스트 추가**

`tests/test_processor.py` 에 추가:
```python
import shutil
import pytest

from silence_removal.detector import detect_silences
from silence_removal.ffmpeg_utils import get_duration
from silence_removal.processor import process_precise

pytestmark_integration = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg 필요"
)


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
```

- [ ] **Step 7: 통합 테스트 통과 확인**

Run: `pytest tests/test_processor.py -v`
Expected: PASS (3 passed) — ffmpeg가 설치돼 있어야 함

- [ ] **Step 8: 커밋**

```bash
git add src/silence_removal/processor.py tests/test_processor.py tests/conftest.py
git commit -m "feat: add precise/copy processing with audio integration test"
```

---

### Task 6: 영상 처리 통합 테스트 (precise + copy)

Task 5의 처리기가 영상에서도 동작하고 A/V 싱크·화질이 유지되는지 검증한다.

**Files:**
- Modify: `tests/test_processor.py`

- [ ] **Step 1: 영상 precise 통합 테스트 추가**

`tests/test_processor.py` 에 추가:
```python
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
```

- [ ] **Step 2: 영상 copy 통합 테스트 추가**

```python
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
```

- [ ] **Step 3: 통합 테스트 통과 확인**

Run: `pytest tests/test_processor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 4: 커밋**

```bash
git add tests/test_processor.py
git commit -m "test: add video precise and copy integration tests"
```

---

### Task 7: CLI — 탐색·오케스트레이션·JSON·종료코드 (`cli.py`)

파일/폴더 탐색과 결과 요약 조립은 순수 함수로 떼어 테스트하고, 전체 실행은 통합으로 확인한다.

**Files:**
- Create: `src/silence_removal/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 탐색/요약 순수 함수 실패 테스트 작성**

`tests/test_cli.py`:
```python
from silence_removal.cli import discover_inputs, build_summary, output_path_for


def test_discover_single_file(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    assert discover_inputs(str(f)) == [str(f)]


def test_discover_folder_filters_media(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    found = discover_inputs(str(tmp_path))
    names = sorted(p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in found)
    assert names == ["a.mp4", "b.wav"]


def test_output_path_default_suffix(tmp_path):
    src = str(tmp_path / "rec.mp4")
    out = output_path_for(src, output_dir=None)
    assert out.endswith("rec_trimmed.mp4")


def test_output_path_with_dir(tmp_path):
    src = str(tmp_path / "rec.mp4")
    out = output_path_for(src, output_dir="/dest")
    assert out.replace("\\", "/").endswith("/dest/rec_trimmed.mp4")


def test_build_summary_counts():
    results = [
        {"status": "ok"},
        {"status": "skipped"},
        {"status": "failed"},
        {"status": "ok"},
    ]
    s = build_summary(results)
    assert s == {"total": 4, "ok": 2, "skipped": 1, "failed": 1}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: CLI 구현 작성**

`src/silence_removal/cli.py`:
```python
"""CLI 진입점: 인자 파싱, 파일/폴더 탐색, 오케스트레이션, JSON·종료코드."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from .detector import detect_silences
from .ffmpeg_utils import (
    FFmpegNotFound,
    ensure_ffmpeg,
    get_duration,
    has_audio,
    has_video,
)
from .processor import process_copy, process_precise
from .segments import compute_keep_segments

MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
              ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_USAGE = 2


def discover_inputs(path: str) -> list[str]:
    """파일이면 그 파일, 폴더면 안의 미디어 파일 목록(정렬)."""
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        found = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isfile(full) and os.path.splitext(name)[1].lower() in MEDIA_EXTS:
                found.append(full)
        return found
    return []


def output_path_for(src: str, output_dir: str | None) -> str:
    """기본 출력 경로: 원본 옆 *_trimmed.확장자, 또는 지정 폴더."""
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    out_name = f"{stem}_trimmed{ext}"
    if output_dir:
        return os.path.join(output_dir, out_name)
    return os.path.join(os.path.dirname(src), out_name)


def build_summary(results: list[dict]) -> dict:
    """결과 목록에서 요약 카운트 생성."""
    summary = {"total": len(results), "ok": 0, "skipped": 0, "failed": 0}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return summary


def _process_one(path: str, args) -> dict:
    """파일 하나 처리. 결과 dict 반환(예외를 던지지 않음)."""
    try:
        if not has_audio(path):
            return {"input": path, "status": "skipped", "reason": "no audio track"}

        silences, total = detect_silences(path, args.threshold, args.min_silence)
        keep = compute_keep_segments(silences, total, args.keep_silence)

        if not silences:
            return {
                "input": path, "status": "ok", "reason": "no silence found",
                "original_sec": total, "output_sec": total, "saved_sec": 0.0,
                "segments_kept": 1, "mode": "none",
            }

        out = output_path_for(path, args.output)
        if os.path.exists(out) and not args.yes and not args.dry_run:
            return {"input": path, "status": "skipped", "reason": "output exists"}

        mode = "copy" if args.copy else "precise"
        kept_sec = sum(s.duration for s in keep)

        if args.dry_run:
            return {
                "input": path, "output": out, "status": "ok",
                "original_sec": total, "output_sec": round(kept_sec, 3),
                "saved_sec": round(total - kept_sec, 3),
                "segments_kept": len(keep), "mode": mode, "dry_run": True,
            }

        vid = has_video(path)
        if mode == "copy":
            with tempfile.TemporaryDirectory() as wd:
                process_copy(path, out, keep, wd)
        else:
            process_precise(path, out, keep, vid)

        out_sec = get_duration(out)
        return {
            "input": path, "output": out, "status": "ok",
            "original_sec": round(total, 3), "output_sec": round(out_sec, 3),
            "saved_sec": round(total - out_sec, 3),
            "segments_kept": len(keep), "mode": mode,
        }
    except Exception as exc:  # noqa: BLE001 - 일괄처리 계속을 위해 포괄 처리
        return {"input": path, "status": "failed", "reason": str(exc)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="silence-removal",
        description="녹화·녹음 파일의 무음 구간을 짧게 줄여 정리합니다.",
        epilog=(
            "예시:\n"
            "  silence-removal recording.mp4\n"
            "  silence-removal ./녹화폴더\n"
            "  silence-removal talk.mp4 --keep-silence 0.5 --copy\n"
            "  silence-removal ./영상들 --dry-run --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", nargs="?", help="파일 또는 폴더 경로")
    p.add_argument("-o", "--output", help="출력 폴더 (기본: 원본 옆 *_trimmed)")
    p.add_argument("--threshold", type=float, default=-30,
                   help="무음 기준 dB (기본: -30)")
    p.add_argument("--min-silence", type=float, default=0.5,
                   help="이 길이(초) 이상만 무음 처리 (기본: 0.5)")
    p.add_argument("--keep-silence", type=float, default=0.3,
                   help="잘라낸 무음에 남길 총 길이(초), 앞뒤 절반씩 (기본: 0.3)")
    p.add_argument("--copy", action="store_true",
                   help="빠른 무손실 모드(키프레임 스냅, 싱크 미세오차 감수)")
    p.add_argument("--dry-run", action="store_true",
                   help="처리 없이 예상 결과만 출력")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="결과를 stdout에 JSON으로 출력")
    p.add_argument("-y", "--yes", action="store_true", help="덮어쓰기 확인 생략")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.input:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    try:
        ensure_ffmpeg()
    except FFmpegNotFound as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    inputs = discover_inputs(args.input)
    if not inputs:
        print(f"처리할 미디어 파일이 없습니다: {args.input}", file=sys.stderr)
        return EXIT_USAGE

    if args.output:
        os.makedirs(args.output, exist_ok=True)

    results = []
    for path in inputs:
        print(f"처리 중: {path}", file=sys.stderr)
        r = _process_one(path, args)
        results.append(r)
        if not args.as_json:
            if r["status"] == "ok":
                saved = r.get("saved_sec", 0.0)
                print(f"  완료 · {saved:.1f}초 절감 · {r.get('mode')}", file=sys.stderr)
            else:
                print(f"  {r['status']}: {r.get('reason', '')}", file=sys.stderr)

    summary = build_summary(results)
    if args.as_json:
        json.dump({"results": results, "summary": summary},
                  sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(
            f"\n요약: 총 {summary['total']} · 성공 {summary['ok']} · "
            f"건너뜀 {summary['skipped']} · 실패 {summary['failed']}",
            file=sys.stderr,
        )

    if summary["failed"] > 0:
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 순수 함수 테스트 통과 확인**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: CLI end-to-end 통합 테스트 추가**

`tests/test_cli.py` 에 추가:
```python
import json as _json
import shutil
import pytest

from silence_removal.cli import main


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 필요")
def test_cli_dry_run_json(audio_with_silence, capsys):
    code = main([audio_with_silence, "--dry-run", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data["summary"]["total"] == 1
    assert data["results"][0]["saved_sec"] > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 필요")
def test_cli_processes_file(audio_with_silence, tmp_path, capsys):
    outdir = tmp_path / "out"
    code = main([audio_with_silence, "-o", str(outdir), "-y", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data["summary"]["ok"] == 1
    produced = data["results"][0]["output"]
    import os
    assert os.path.exists(produced)


def test_cli_no_args_shows_help_and_usage_code():
    assert main([]) == 2
```

> 참고: `audio_with_silence` 픽스처는 `tests/conftest.py`에 있어 `test_cli.py`에서도 자동으로 쓸 수 있다.

- [ ] **Step 6: 통합 테스트 통과 확인**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (8 passed)

- [ ] **Step 7: 전체 테스트 실행**

Run: `pytest -v`
Expected: 전부 PASS

- [ ] **Step 8: 실제 CLI 수동 확인**

Run: `silence-removal --help`
Expected: 사용법·옵션·예시 출력

- [ ] **Step 9: 커밋**

```bash
git add src/silence_removal/cli.py tests/test_cli.py
git commit -m "feat: add CLI with discovery, orchestration, json output"
```

---

### Task 8: README 및 마무리

**Files:**
- Create: `README.md`

- [ ] **Step 1: README 작성**

`README.md`:
```markdown
# silence-removal

녹화·녹음 파일(영상+오디오)의 무음 구간을 짧게 줄여 정리하는 CLI 도구.

## 요구사항
- Python 3.10+
- ffmpeg, ffprobe (PATH에 등록)
  - Windows: `winget install Gyan.FFmpeg`

## 설치
```bash
pip install -e .
```

## 사용법
```bash
silence-removal recording.mp4               # 파일 하나
silence-removal ./녹화폴더                    # 폴더 일괄
silence-removal talk.mp4 --keep-silence 0.5  # 무음 0.5초 남김
silence-removal talk.mp4 --copy              # 빠른 무손실 모드
silence-removal ./영상들 --dry-run --json    # 예상 결과만(에이전트용)
```

## 주요 옵션
| 옵션 | 설명 | 기본 |
|------|------|------|
| `--threshold DB` | 무음 기준 dB | -30 |
| `--min-silence SEC` | 이 길이 이상만 무음 처리 | 0.5 |
| `--keep-silence SEC` | 잘라낸 무음에 남길 총 길이(앞뒤 절반씩) | 0.3 |
| `--copy` | 무손실 스트림복사(빠름, 싱크 미세오차 감수) | precise |
| `--dry-run` | 처리 없이 예상 결과만 | - |
| `--json` | stdout에 JSON 출력 | - |

## 모드
- **precise (기본)**: 재인코딩. A/V 싱크 100% 보장, 하드웨어 인코더 자동 사용.
- **copy (`--copy`)**: 스트림 복사. 무손실·초고속, 컷이 많으면 미세 싱크오차 가능.

## 종료 코드
- `0` 전체 성공 / `1` 일부 실패 / `2` 사용법·입력 오류
```

- [ ] **Step 2: 전체 테스트 최종 확인**

Run: `pytest -q`
Expected: 전부 PASS

- [ ] **Step 3: 커밋**

```bash
git add README.md
git commit -m "docs: add README"
```

---

## Self-Review 결과

**Spec 커버리지 확인:**
- CLI / Python+ffmpeg → Task 1, 7 ✓
- 영상+오디오, 파일+폴더 일괄 → `discover_inputs`(Task 7), 영상/오디오 처리(Task 5,6) ✓
- 무음 감지(threshold/min-silence) → Task 3 ✓
- 두뇌 `segments.py` 순수함수 + keep-silence 절반배분 → Task 2 ✓
- precise 기본(싱크 보장) + HW 가속 + copy 옵션 → Task 4, 5, 6 ✓
- 에이전트 친화(--json, 종료코드, stdout/stderr 분리, --dry-run) → Task 7 ✓
- help / 인자 없으면 help+코드2 → Task 7 ✓
- 에러 처리(ffmpeg 없음, 오디오 없음, 일괄 계속, 무음 없음, 덮어쓰기) → Task 7 `_process_one`/`main` ✓
- 테스트(순수함수 단위 + 합성샘플 통합) → 전 Task ✓

**Placeholder 스캔:** 없음. 모든 코드 단계에 실제 코드 포함.

**타입/시그니처 일관성:** `Interval`(segments), `detect_silences`/`parse_silences`(detector), `build_filter_complex`/`process_precise`/`process_copy`(processor), `discover_inputs`/`output_path_for`/`build_summary`/`main`(cli) — Task 간 이름·인자 일치 확인.

**남은 위험/주의:**
- `copy` 모드 출력 컨테이너는 원본 확장자를 따르되, 스트림복사 호환성을 위해 통합 테스트는 `.mkv`를 사용. 실사용에서 mp4→mp4 copy가 코덱 비호환일 경우 mkv 폴백을 고려(향후 개선 항목, 본 계획 범위 밖).
- Windows에서 `filter_complex`가 매우 길어지면(수백 컷) 명령행 길이 제한에 걸릴 수 있음. 필요 시 `-filter_complex_script`로 파일 전달로 전환(향후 개선).
