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


def test_discover_folder_excludes_trimmed_outputs(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "a_trimmed.mp4").write_bytes(b"x")
    found = discover_inputs(str(tmp_path))
    names = sorted(p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in found)
    assert names == ["a.mp4"]


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
