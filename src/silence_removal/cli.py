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
            "  silence-removal ./nokhwa_folder\n"
            "  silence-removal talk.mp4 --keep-silence 0.5 --copy\n"
            "  silence-removal ./videos --dry-run --json\n"
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
