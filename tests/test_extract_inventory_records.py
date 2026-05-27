from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import types
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

import pytest

from anyfile_wiki.cli import main as cli_main
from anyfile_wiki.inventory import Inventory
from anyfile_wiki.parse import ExtractResult, ParseJob, extract_jobs
from anyfile_wiki.policy import AccessDecision
from anyfile_wiki.scan import ScanEntry


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


def _entry(path: Path, access_policy: str = "allow") -> ScanEntry:
    path.write_text(f"fixture for {path.name}", encoding="utf-8")
    return ScanEntry(
        path=str(path),
        name=path.name,
        extension=path.suffix.lower(),
        is_dir=False,
        exists_now=True,
        size_bytes=path.stat().st_size,
        mtime=1.0,
        ctime=1.0,
        decision=_decision(path, access_policy),
        last_seen_at="2026-05-27T12:00:00+00:00",
        extra={"fixture": "extract-records"},
    )


def _extract_result(
    path: Path,
    *,
    parser: str,
    status: str,
    created_at: str,
    output_path: Path | None = None,
    error: str | None = None,
    embedding_allowed: bool = True,
) -> ExtractResult:
    return ExtractResult(
        path=str(path),
        parser=parser,
        status=status,
        output_path=str(output_path) if output_path else None,
        error=error,
        embedding_allowed=embedding_allowed,
        created_at=created_at,
    )


def _field(record, *names):
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return None
    for name in names:
        try:
            return record[name]
        except (IndexError, KeyError, TypeError):
            pass
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return None


def _to_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    elif hasattr(value, "value") and not isinstance(value, (str, bool, int, float)):
        value = value.value
    return str(value).split(".")[-1].lower().replace("-", "_").replace(" ", "_")


def _as_records(value) -> list:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Path)):
        return []
    if isinstance(value, Mapping):
        if _field(value, "path", "file_path", "source_path") is not None:
            return [value]
        for key in ("records", "items", "results", "extracts", "extractions"):
            if key in value:
                return _as_records(value[key])
        return []
    if is_dataclass(value):
        return [asdict(value)]
    if hasattr(value, "__dict__") and _field(value, "path", "file_path", "source_path"):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return []


def _path_text(record) -> str:
    return str(
        _field(
            record,
            "path",
            "source_path",
            "file_path",
            "filepath",
            "document_path",
        )
        or ""
    )


def _path_names(records: Iterable) -> list[str]:
    return [Path(_path_text(record)).name for record in records]


def _status(record) -> str | None:
    return _to_text(_field(record, "status", "state", "result_status", "outcome"))


def _parser(record) -> str | None:
    return _to_text(_field(record, "parser", "parser_name", "extractor"))


def _created_at(record) -> str:
    return str(_field(record, "created_at", "extracted_at", "timestamp", "updated_at") or "")


def _record_extract_results(inventory: Inventory, results: list[ExtractResult]) -> None:
    method_names = (
        "upsert_extract_results",
        "record_extract_results",
        "write_extract_results",
        "save_extract_results",
        "insert_extract_results",
        "add_extract_results",
        "upsert_extractions",
        "record_extractions",
        "write_extractions",
        "save_extractions",
    )
    last_error: Exception | None = None
    for method_name in method_names:
        method = getattr(inventory, method_name, None)
        if method is None:
            continue
        try:
            saved = method(results)
        except TypeError as exc:
            last_error = exc
            continue
        if isinstance(saved, int):
            assert int(saved) == len(results)
        elif saved is not None and hasattr(saved, "__len__"):
            assert len(saved) == len(results)
        return
    pytest.fail(f"Inventory should persist ExtractResult lists; last error: {last_error}")


def _query_extract_records(
    inventory: Inventory,
    *,
    limit: int = 20,
    status: str | None = None,
    parser: str | None = None,
    path: Path | str | None = None,
) -> list:
    method_names = (
        "list_extract_results",
        "list_extraction_results",
        "list_extracts",
        "list_extractions",
        "recent_extract_results",
        "recent_extractions",
        "extract_results",
        "extractions",
    )
    path_keys = ("path", "source_path", "file_path", "filepath")
    last_error: Exception | None = None
    for method_name in method_names:
        method = getattr(inventory, method_name, None)
        if method is None:
            continue
        kwargs_options: list[dict[str, object]] = [{"limit": limit}]
        if status is not None:
            kwargs_options = [{**kwargs, "status": status} for kwargs in kwargs_options]
        if parser is not None:
            kwargs_options = [{**kwargs, "parser": parser} for kwargs in kwargs_options]
        if path is not None:
            kwargs_options = [
                {**kwargs, path_key: str(path)}
                for kwargs in kwargs_options
                for path_key in path_keys
            ]
        for kwargs in kwargs_options:
            try:
                records = _as_records(method(**kwargs))
            except TypeError as exc:
                last_error = exc
                continue
            return records

    specialized = _query_specialized_extract_records(
        inventory, limit=limit, status=status, parser=parser, path=path
    )
    if specialized is not None:
        return specialized

    pytest.fail(f"Inventory should query recent extraction records; last error: {last_error}")


def _query_specialized_extract_records(
    inventory: Inventory,
    *,
    limit: int,
    status: str | None,
    parser: str | None,
    path: Path | str | None,
) -> list | None:
    if status is not None and parser is None and path is None:
        return _call_specialized(
            inventory,
            ("list_extract_results_by_status", "extract_results_by_status"),
            status,
            limit,
        )
    if parser is not None and status is None and path is None:
        return _call_specialized(
            inventory,
            ("list_extract_results_by_parser", "extract_results_by_parser"),
            parser,
            limit,
        )
    if path is not None and status is None and parser is None:
        return _call_specialized(
            inventory,
            ("list_extract_results_by_path", "extract_results_by_path"),
            str(path),
            limit,
        )
    return None


def _call_specialized(
    inventory: Inventory, method_names: tuple[str, ...], value: str, limit: int
) -> list | None:
    for method_name in method_names:
        method = getattr(inventory, method_name, None)
        if method is None:
            continue
        for call in (
            lambda: method(value, limit=limit),
            lambda: method(value, limit),
            lambda: method(value),
        ):
            try:
                return _as_records(call())
            except TypeError:
                continue
    return None


def _seed_extract_results(tmp_path: Path) -> tuple[Path, list[ExtractResult]]:
    notes = tmp_path / "notes.md"
    paper = tmp_path / "paper.pdf"
    slides = tmp_path / "slides.pptx"
    output = tmp_path / "extract"
    output.mkdir()
    for path in (notes, paper, slides):
        path.write_text(path.name, encoding="utf-8")
    results = [
        _extract_result(
            notes,
            parser="direct_text",
            status="ok",
            output_path=output / "notes.md",
            created_at="2026-05-27T10:00:00+00:00",
        ),
        _extract_result(
            paper,
            parser="markitdown",
            status="ok",
            output_path=output / "paper.md",
            created_at="2026-05-27T11:00:00+00:00",
        ),
        _extract_result(
            slides,
            parser="markitdown",
            status="error",
            error="conversion failed",
            created_at="2026-05-27T12:00:00+00:00",
            embedding_allowed=False,
        ),
    ]
    inventory_path = tmp_path / "inventory.sqlite"
    with Inventory(inventory_path) as inventory:
        _record_extract_results(inventory, results)
    return inventory_path, results


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


def _run_extract_records_cli(inventory_path: Path) -> tuple[list[str], str, str]:
    candidates = [
        ["extracts", "--inventory", str(inventory_path), "--limit", "20"],
        ["extract-status", "--inventory", str(inventory_path), "--limit", "20"],
        ["extract-results", "--inventory", str(inventory_path), "--limit", "20"],
        ["extractions", "--inventory", str(inventory_path), "--limit", "20"],
        ["extracts", "--inventory", str(inventory_path)],
        ["extract-status", "--inventory", str(inventory_path)],
    ]
    errors = []
    for argv in candidates:
        code, stdout, stderr = _run_cli(argv)
        if code == 0:
            return argv, stdout, stderr
        errors.append((argv, code, stderr))
    pytest.fail(f"CLI should expose extraction status/list command; attempts: {errors}")


def _manifest_records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _assert_stat_count(text: str, status: str, expected: int) -> None:
    status_then_count = rf"\b{re.escape(status)}\b[^\n\d]{{0,40}}{expected}\b"
    count_then_status = rf"\b{expected}\b[^\nA-Za-z_]{{0,40}}\b{re.escape(status)}\b"
    assert re.search(status_then_count, text) or re.search(count_then_status, text), text


def test_inventory_persists_and_queries_recent_extract_results(tmp_path):
    inventory_path, _results = _seed_extract_results(tmp_path)

    with Inventory(inventory_path) as inventory:
        recent = _query_extract_records(inventory, limit=3)
        assert _path_names(recent)[:3] == ["slides.pptx", "paper.pdf", "notes.md"]
        assert [_created_at(record) for record in recent[:3]] == sorted(
            (_created_at(record) for record in recent[:3]), reverse=True
        )

        ok_records = _query_extract_records(inventory, status="ok", limit=10)
        assert _path_names(ok_records) == ["paper.pdf", "notes.md"]
        assert {_status(record) for record in ok_records} == {"ok"}

        markitdown_records = _query_extract_records(inventory, parser="markitdown", limit=10)
        assert _path_names(markitdown_records) == ["slides.pptx", "paper.pdf"]
        assert {_parser(record) for record in markitdown_records} == {"markitdown"}

        paper_records = _query_extract_records(
            inventory, path=tmp_path / "paper.pdf", limit=10
        )
        assert _path_names(paper_records) == ["paper.pdf"]
        assert _status(paper_records[0]) == "ok"
        assert _parser(paper_records[0]) == "markitdown"


def test_cli_extract_records_command_shows_stats_and_list(tmp_path):
    inventory_path, _results = _seed_extract_results(tmp_path)

    _argv, stdout, stderr = _run_extract_records_cli(inventory_path)

    assert stderr == ""
    output = stdout.lower()
    _assert_stat_count(output, "ok", 2)
    _assert_stat_count(output, "error", 1)
    assert "direct_text" in output
    assert "markitdown" in output
    assert "notes.md" in output
    assert "paper.pdf" in output
    assert "slides.pptx" in output


def test_extract_cli_writes_manifest_and_inventory_records(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    allowed = root / "allowed.md"
    summary = root / "summary.txt"
    metadata_only = root / "metadata-only.md"
    inventory_path = tmp_path / "inventory.sqlite"
    with Inventory(inventory_path) as inventory:
        inventory.upsert_entries(
            [
                _entry(allowed, "allow"),
                _entry(summary, "allow"),
                _entry(metadata_only, "metadata_only"),
            ]
        )

    output_dir = tmp_path / "extract"
    manifest_path = output_dir / "extract-manifest.jsonl"
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
    assert "manifest" in stdout.lower()
    manifest = _manifest_records(manifest_path)
    assert _path_names(manifest) == ["allowed.md", "summary.txt"]
    assert {record["status"] for record in manifest} == {"ok"}

    with Inventory(inventory_path) as inventory:
        records = _query_extract_records(inventory, limit=10)
    by_name = {Path(_path_text(record)).name: record for record in records}
    assert {"allowed.md", "summary.txt"} <= set(by_name)
    assert "metadata-only.md" not in by_name
    for name in ("allowed.md", "summary.txt"):
        record = by_name[name]
        assert _status(record) == "ok"
        assert _parser(record) == "direct_text"
        output_path = _field(record, "output_path", "artifact_path")
        assert output_path
        assert Path(str(output_path)).exists()


def test_markitdown_success_uses_fake_module_without_real_dependency(tmp_path, monkeypatch):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    converted_paths: list[str] = []

    class FakeMarkItDown:
        def convert(self, path: str):
            converted_paths.append(path)
            return types.SimpleNamespace(text_content="# Converted\n\nfrom fake module")

    monkeypatch.setitem(
        sys.modules,
        "markitdown",
        types.SimpleNamespace(MarkItDown=FakeMarkItDown),
    )

    result = extract_jobs(
        [ParseJob(source, "markitdown", "allow fixture", True)],
        tmp_path / "extract",
    )[0]

    assert converted_paths == [str(source)]
    assert result.status == "ok"
    assert result.parser == "markitdown"
    assert result.error is None
    assert result.output_path is not None
    assert Path(result.output_path).read_text(encoding="utf-8") == (
        "# Converted\n\nfrom fake module"
    )
