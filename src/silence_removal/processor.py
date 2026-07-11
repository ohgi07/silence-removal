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
