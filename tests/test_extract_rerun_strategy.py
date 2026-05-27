from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import types
from dataclasses import fields
from pathlib import Path

import pytest

from pfkb.cli import main as cli_main
from pfkb.inventory import Inventory
from pfkb.parse import ExtractResult
from pfkb.policy import AccessDecision
from pfkb.scan import ScanEntry


def _decision(path: Path, access_policy: str = "allow") -> AccessDecision:
    is_excluded = access_policy == "deny"
    read_allowed = access_policy in {"allow", "no_embedding"}
    return AccessDecision(
        path=path.resolve().as_posix(),
        is_dir=False,
        access_policy=access_policy,
        policy_source=f"test.{access_policy}",
        reason=f"{access_policy} fixture",
        is_read_allowed=False if is_excluded else read_allowed,
        is_extract_allowed=False if is_excluded else read_allowed,
        is_index_allowed=not is_excluded and access_policy != "metadata_only",
        is_embedding_allowed=access_policy == "allow",
        metadata_only=access_policy == "metadata_only",
        is_excluded=is_excluded,
    )


def _entry_from_existing(path: Path, access_policy: str = "allow") -> ScanEntry:
    stat = path.stat()
    return ScanEntry(
        path=str(path),
        name=path.name,
        extension=path.suffix.lower(),
        is_dir=False,
        exists_now=True,
        size_bytes=stat.st_size,
        mtime=stat.st_mtime,
        ctime=stat.st_ctime,
        decision=_decision(path, access_policy),
        last_seen_at="2026-05-27T12:00:00+00:00",
        extra={"fixture": "extract-rerun-strategy"},
    )


def _write_source(path: Path, content: str | bytes, access_policy: str = "allow") -> ScanEntry:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return _entry_from_existing(path, access_policy)


def _seed_inventory(tmp_path: Path, entries: list[ScanEntry]) -> Path:
    inventory_path = tmp_path / "inventory.sqlite"
    with Inventory(inventory_path) as inventory:
        assert inventory.upsert_entries(entries) == len(entries)
    return inventory_path


def _refresh_inventory_entry(inventory_path: Path, path: Path) -> None:
    with Inventory(inventory_path) as inventory:
        assert inventory.upsert_entries([_entry_from_existing(path)]) == 1


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


def _extract_result(
    path: Path,
    *,
    parser: str = "direct_text",
    status: str = "ok",
    output_path: Path | None = None,
    error: str | None = None,
    created_at: str = "2026-05-27T00:00:00+00:00",
) -> ExtractResult:
    values = {
        "path": str(path),
        "parser": parser,
        "status": status,
        "output_path": str(output_path) if output_path else None,
        "error": error,
        "embedding_allowed": True,
        "created_at": created_at,
    }
    if path.exists():
        stat = path.stat()
        values.update(
            {
                "source_size": stat.st_size,
                "source_size_bytes": stat.st_size,
                "size_bytes": stat.st_size,
                "source_mtime": stat.st_mtime,
                "mtime": stat.st_mtime,
            }
        )
    return ExtractResult(**{field.name: values[field.name] for field in fields(ExtractResult)})


def _watch_content_reads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    watched_paths: set[Path],
    forbidden_paths: set[Path] | None = None,
) -> set[Path]:
    watched = {path.resolve() for path in watched_paths}
    forbidden = {path.resolve() for path in forbidden_paths or set()}
    read_paths: set[Path] = set()
    real_open = Path.open
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text

    def record(path: Path) -> None:
        resolved = path.resolve()
        if resolved in forbidden:
            raise AssertionError(f"extract should not read up-to-date source: {path}")
        if resolved in watched:
            read_paths.add(resolved)

    def guarded_open(self: Path, mode="r", *args, **kwargs):
        if "r" in str(mode) or "+" in str(mode):
            record(self)
        return real_open(self, mode, *args, **kwargs)

    def guarded_read_bytes(self: Path, *args, **kwargs):
        record(self)
        return real_read_bytes(self, *args, **kwargs)

    def guarded_read_text(self: Path, *args, **kwargs):
        record(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    return read_paths


def _run_initial_extract(inventory_path: Path, output_dir: Path) -> tuple[str, str]:
    manifest_path = output_dir / "initial.jsonl"
    code, stdout, stderr = _run_cli(
        [
            "extract",
            "--inventory",
            str(inventory_path),
            "--out",
            str(output_dir),
            "--manifest",
            str(manifest_path),
            "--limit",
            "20",
        ]
    )
    assert code == 0, stderr
    return stdout, stderr


def _run_extract(inventory_path: Path, output_dir: Path, *extra_args: str) -> tuple[int, str, str]:
    manifest_path = output_dir / f"run-{abs(hash(extra_args))}.jsonl"
    return _run_cli(
        [
            "extract",
            "--inventory",
            str(inventory_path),
            "--out",
            str(output_dir),
            "--manifest",
            str(manifest_path),
            "--limit",
            "20",
            *extra_args,
        ]
    )


def _run_retry_failed_extract(
    inventory_path: Path,
    output_dir: Path,
) -> tuple[list[str], int, str, str]:
    candidates = [
        ["--retry-failed"],
        ["--retry-failures"],
        ["--retry-errors"],
        ["--rerun-failed"],
        ["--rerun-failures"],
        ["--failed"],
        ["--retry", "failed"],
        ["--retry", "failures"],
        ["--retry", "errors"],
        ["--retry", "error"],
        ["--retry", "error,skipped"],
        ["--rerun", "failed"],
        ["--rerun", "error,skipped"],
    ]
    attempts: list[tuple[list[str], int, str]] = []
    for flags in candidates:
        code, stdout, stderr = _run_extract(inventory_path, output_dir, *flags)
        stderr_lower = stderr.lower()
        unsupported = code == 2 and (
            "unrecognized arguments" in stderr_lower
            or "invalid choice" in stderr_lower
            or "expected one argument" in stderr_lower
        )
        if not unsupported:
            return flags, code, stdout, stderr
        attempts.append((flags, code, stderr))
    pytest.fail(f"extract CLI should expose --retry-failed or an equivalent option: {attempts}")


def _canonical_count_key(key: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if normalized in {"planned", "planned_count", "to_extract", "to_extract_count"}:
        return "planned"
    if normalized in {"skipped", "skipped_count", "skip", "skip_count"}:
        return "skipped"
    if normalized in {
        "up_to_date",
        "up_to_date_count",
        "uptodate",
        "uptodate_count",
    }:
        return "up_to_date"
    return None


def _json_counts(stdout: str) -> dict[str, int]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    counts: dict[str, int] = {}

    def visit(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                canonical = _canonical_count_key(str(key))
                if canonical and isinstance(item, int) and not isinstance(item, bool):
                    counts[canonical] = item
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return counts


def _assert_cli_count(stdout: str, key: str, expected: int) -> None:
    counts = _json_counts(stdout)
    if counts.get(key) == expected:
        return

    label_patterns = {
        "planned": [r"planned", r"to[_ -]?extract"],
        "skipped": [r"skipped"],
        "up_to_date": [r"up[_ -]?to[_ -]?date", r"uptodate"],
    }[key]
    for label in label_patterns:
        if re.search(rf"\b{label}\b[^\n0-9]{{0,60}}\b{expected}\b", stdout, re.I):
            return
        if re.search(rf"\b{expected}\b[^\nA-Za-z0-9]{{0,60}}\b{label}\b", stdout, re.I):
            return
    pytest.fail(f"expected {key} count {expected} in extract output:\n{stdout}")


def test_default_extract_skips_ok_sources_when_size_and_mtime_are_unchanged(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    note = root / "note.md"
    guide = root / "guide.txt"
    inventory_path = _seed_inventory(
        tmp_path,
        [
            _write_source(note, "# note\n"),
            _write_source(guide, "guide\n"),
        ],
    )
    output_dir = tmp_path / "extract"
    _run_initial_extract(inventory_path, output_dir)

    read_paths = _watch_content_reads(
        monkeypatch,
        watched_paths={note, guide},
        forbidden_paths={note, guide},
    )
    code, stdout, stderr = _run_extract(inventory_path, output_dir)

    assert code == 0, stderr
    assert read_paths == set()
    _assert_cli_count(stdout, "planned", 0)
    _assert_cli_count(stdout, "up_to_date", 2)


def test_force_extract_reruns_all_allowed_sources_even_when_unchanged(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    note = root / "note.md"
    guide = root / "guide.txt"
    inventory_path = _seed_inventory(
        tmp_path,
        [
            _write_source(note, "# note\n"),
            _write_source(guide, "guide\n"),
        ],
    )
    output_dir = tmp_path / "extract"
    _run_initial_extract(inventory_path, output_dir)

    read_paths = _watch_content_reads(monkeypatch, watched_paths={note, guide})
    code, stdout, stderr = _run_extract(inventory_path, output_dir, "--force")

    assert code == 0, stderr
    assert read_paths == {note.resolve(), guide.resolve()}
    _assert_cli_count(stdout, "planned", 2)
    _assert_cli_count(stdout, "skipped", 0)


def test_retry_failed_extract_only_reruns_latest_error_and_skipped_sources(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    ok_source = root / "ok.md"
    error_source = root / "missing.txt"
    skipped_source = root / "paper.pdf"
    inventory_path = _seed_inventory(
        tmp_path,
        [
            _write_source(ok_source, "already extracted\n"),
            _write_source(error_source, "will be missing for first extract\n"),
            _write_source(skipped_source, b"%PDF-1.4 fake"),
        ],
    )
    error_source.unlink()
    monkeypatch.setitem(sys.modules, "markitdown", None)
    output_dir = tmp_path / "extract"
    code, _stdout, _stderr = _run_extract(inventory_path, output_dir)
    assert code == 1

    error_source.write_text("now available\n", encoding="utf-8")
    _refresh_inventory_entry(inventory_path, error_source)
    converted_paths: list[str] = []

    class FakeMarkItDown:
        def convert(self, path: str):
            converted_paths.append(path)
            return types.SimpleNamespace(text_content="converted pdf")

    monkeypatch.setitem(
        sys.modules,
        "markitdown",
        types.SimpleNamespace(MarkItDown=FakeMarkItDown),
    )
    read_paths = _watch_content_reads(
        monkeypatch,
        watched_paths={ok_source, error_source},
        forbidden_paths={ok_source},
    )

    flags, code, stdout, stderr = _run_retry_failed_extract(inventory_path, output_dir)

    assert flags
    assert code == 0, stderr
    assert read_paths == {error_source.resolve()}
    assert converted_paths == [str(skipped_source)]
    _assert_cli_count(stdout, "planned", 2)


def test_default_extract_reruns_ok_sources_when_size_or_mtime_changes(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    unchanged = root / "unchanged.md"
    size_changed = root / "size-changed.md"
    mtime_changed = root / "mtime-changed.md"
    inventory_path = _seed_inventory(
        tmp_path,
        [
            _write_source(unchanged, "stable\n"),
            _write_source(size_changed, "short\n"),
            _write_source(mtime_changed, "same-size\n"),
        ],
    )
    output_dir = tmp_path / "extract"
    _run_initial_extract(inventory_path, output_dir)

    size_changed.write_text("a much longer body than before\n", encoding="utf-8")
    _refresh_inventory_entry(inventory_path, size_changed)

    stat = mtime_changed.stat()
    os.utime(mtime_changed, (stat.st_atime, stat.st_mtime + 3600))
    _refresh_inventory_entry(inventory_path, mtime_changed)

    read_paths = _watch_content_reads(
        monkeypatch,
        watched_paths={unchanged, size_changed, mtime_changed},
        forbidden_paths={unchanged},
    )
    code, stdout, stderr = _run_extract(inventory_path, output_dir)

    assert code == 0, stderr
    assert read_paths == {size_changed.resolve(), mtime_changed.resolve()}
    _assert_cli_count(stdout, "planned", 2)
    _assert_cli_count(stdout, "up_to_date", 1)
