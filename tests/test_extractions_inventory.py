from __future__ import annotations

import contextlib
import io
from pathlib import Path

from anyfile_wiki.cli import main as cli_main
from anyfile_wiki.inventory import Inventory
from anyfile_wiki.parse import ExtractResult


def _result(path: Path, parser: str, status: str, created_at: str) -> ExtractResult:
    return ExtractResult(
        path=str(path),
        parser=parser,
        status=status,
        output_path=str(path.with_suffix(".md")) if status == "ok" else None,
        error=None if status == "ok" else "parser unavailable",
        embedding_allowed=True,
        created_at=created_at,
    )


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


def test_inventory_persists_and_filters_extract_results(tmp_path):
    inventory_path = tmp_path / "inventory.sqlite"
    note = tmp_path / "note.md"
    pdf = tmp_path / "paper.pdf"
    results = [
        _result(note, "direct_text", "ok", "2026-05-27T01:00:00+00:00"),
        _result(pdf, "markitdown", "skipped", "2026-05-27T02:00:00+00:00"),
    ]

    with Inventory(inventory_path) as inventory:
        assert inventory.add_extract_results(results) == 2
        assert inventory.extract_stats() == {"ok": 1, "skipped": 1}
        assert [record["path"] for record in inventory.list_extracts(limit=2)] == [str(pdf), str(note)]
        assert [record["path"] for record in inventory.list_extracts(status="ok")] == [str(note)]
        assert [record["path"] for record in inventory.list_extracts(parser="markitdown")] == [str(pdf)]
        assert [record["path"] for record in inventory.list_extracts(path=note)] == [str(note)]


def test_extracts_cli_lists_persisted_results(tmp_path):
    inventory_path = tmp_path / "inventory.sqlite"
    note = tmp_path / "note.md"
    with Inventory(inventory_path) as inventory:
        inventory.add_extract_results([_result(note, "direct_text", "ok", "2026-05-27T01:00:00+00:00")])

    code, stdout, stderr = _run_cli(["extracts", "--inventory", str(inventory_path), "--stats"])

    assert code == 0, stderr
    assert "ok" in stdout
    assert "direct_text" in stdout
    assert str(note) in stdout
