from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys

from anyfile_wiki.cli import main as cli_main
from anyfile_wiki.inventory import Inventory
from anyfile_wiki.policy import PolicyEngine
from anyfile_wiki.scan import scan_paths


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = cli_main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        else:
            code = int(result)
    return code, stdout.getvalue(), stderr.getvalue()


def _scan(root: Path, inventory_path: Path) -> None:
    engine = PolicyEngine({"allow": {"paths": [str(root)]}})
    result = scan_paths([root], engine)
    with Inventory(inventory_path) as inventory:
        inventory.upsert_entries(result.entries)


def _manifest_records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_extract_skips_unchanged_successful_sources_by_default(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.md"
    note.write_text("hello", encoding="utf-8")
    inventory_path = tmp_path / "inventory.sqlite"
    _scan(root, inventory_path)

    first_out = tmp_path / "extract1"
    code, stdout, stderr = _run_cli(["extract", "--inventory", str(inventory_path), "--out", str(first_out)])
    assert code == 0, stderr
    assert "planned: 1" in stdout
    assert "ok: 1" in stdout

    second_out = tmp_path / "extract2"
    code, stdout, stderr = _run_cli(["extract", "--inventory", str(inventory_path), "--out", str(second_out)])
    assert code == 0, stderr
    assert "planned: 0" in stdout
    assert "skipped: 1" in stdout
    assert "up_to_date: 1" in stdout
    manifest = _manifest_records(second_out / "extract-manifest.jsonl")
    assert manifest[0]["status"] == "up_to_date"
    assert manifest[0]["skip_reason"] == "source unchanged"


def test_extract_reprocesses_changed_sources_and_force_overrides_skip(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.md"
    note.write_text("hello", encoding="utf-8")
    inventory_path = tmp_path / "inventory.sqlite"
    _scan(root, inventory_path)

    code, _, stderr = _run_cli(["extract", "--inventory", str(inventory_path), "--out", str(tmp_path / "extract1")])
    assert code == 0, stderr

    code, stdout, stderr = _run_cli(
        ["extract", "--inventory", str(inventory_path), "--out", str(tmp_path / "extract-force"), "--force"]
    )
    assert code == 0, stderr
    assert "planned: 1" in stdout

    note.write_text("hello changed and longer", encoding="utf-8")
    _scan(root, inventory_path)
    code, stdout, stderr = _run_cli(["extract", "--inventory", str(inventory_path), "--out", str(tmp_path / "extract2")])
    assert code == 0, stderr
    assert "planned: 1" in stdout
    assert "ok: 1" in stdout


def test_extract_filters_by_extension_and_max_source_size(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    small = root / "small.txt"
    large = root / "large.md"
    ignored = root / "ignored.log"
    small.write_text("small", encoding="utf-8")
    large.write_text("x" * 2048, encoding="utf-8")
    ignored.write_text("ignored", encoding="utf-8")
    inventory_path = tmp_path / "inventory.sqlite"
    _scan(root, inventory_path)

    out_dir = tmp_path / "extract-filtered"
    code, stdout, stderr = _run_cli(
        [
            "extract",
            "--inventory",
            str(inventory_path),
            "--out",
            str(out_dir),
            "--extensions",
            ".txt,.md",
            "--max-source-mb",
            "0.001",
        ]
    )

    assert code == 0, stderr
    assert "planned: 1" in stdout
    manifest = _manifest_records(out_dir / "extract-manifest.jsonl")
    assert [Path(record["path"]).name for record in manifest] == ["small.txt"]


def test_retry_failed_only_plans_latest_failed_or_skipped_records(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.md"
    pdf = root / "paper.pdf"
    note.write_text("hello", encoding="utf-8")
    pdf.write_text("fake pdf", encoding="utf-8")
    inventory_path = tmp_path / "inventory.sqlite"
    _scan(root, inventory_path)
    monkeypatch.setitem(sys.modules, "markitdown", None)

    code, stdout, stderr = _run_cli(["extract", "--inventory", str(inventory_path), "--out", str(tmp_path / "extract1")])
    assert code == 0, stderr
    assert "ok: 1" in stdout
    assert "skipped: 1" in stdout

    code, stdout, stderr = _run_cli(
        ["extract", "--inventory", str(inventory_path), "--out", str(tmp_path / "retry"), "--retry-failed"]
    )
    assert code == 0, stderr
    assert "planned: 1" in stdout
    assert "up_to_date: 1" in stdout
    manifest = _manifest_records(tmp_path / "retry" / "extract-manifest.jsonl")
    statuses_by_name = {Path(record["path"]).name: record["status"] for record in manifest}
    assert statuses_by_name["paper.pdf"] == "skipped"
    assert statuses_by_name["note.md"] == "up_to_date"
