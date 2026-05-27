from __future__ import annotations

from pathlib import Path

from anyfile_wiki.inventory import Inventory
from anyfile_wiki.parse import build_parse_jobs
from anyfile_wiki.policy import PolicyEngine
from anyfile_wiki.report import summarize_by_policy, write_scan_plan
from anyfile_wiki.roots import discover_candidate_roots
from anyfile_wiki.scan import scan_paths


def test_inventory_lists_and_fetches_scanned_records(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    allowed = root / "notes.md"
    denied = root / "secret.pem"
    allowed.write_text("hello", encoding="utf-8")
    denied.write_text("secret", encoding="utf-8")

    engine = PolicyEngine(
        {
            "deny": {"extensions": [".pem"]},
            "allow": {"paths": [str(root)]},
        }
    )
    result = scan_paths([root], engine)
    inventory_path = tmp_path / "inventory.sqlite"

    with Inventory(inventory_path) as inventory:
        assert inventory.upsert_entries(result.entries) == 3
        assert inventory.stats()["allow"] == 2
        assert inventory.stats()["deny"] == 1

        denied_records = inventory.list_files(access_policy="deny")
        assert len(denied_records) == 1
        assert denied_records[0]["path"] == str(denied)

        fetched = inventory.get_file(allowed)
        assert fetched is not None
        assert fetched["access_policy"] == "allow"
        assert fetched["is_read_allowed"] is True


def test_scan_plan_contains_policy_aggregation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "notes.md").write_text("hello", encoding="utf-8")
    (root / "secret.pem").write_text("secret", encoding="utf-8")

    engine = PolicyEngine(
        {
            "deny": {"extensions": [".pem"]},
            "allow": {"paths": [str(root)]},
        }
    )
    result = scan_paths([root], engine)
    assert summarize_by_policy(result.entries) == {"allow": 2, "deny": 1}

    report_path = tmp_path / "scan-plan.md"
    write_scan_plan(result, report_path)
    report = report_path.read_text(encoding="utf-8")
    assert "## Policy Counts" in report
    assert "`allow`: 2" in report
    assert "`deny`: 1" in report


def test_discover_candidate_roots_is_safe():
    roots = discover_candidate_roots(existing_only=False)
    names = {root.name for root in roots}
    assert "home" in names
    assert "documents" in names
    assert all(isinstance(root.path, Path) for root in roots)


def test_parse_jobs_are_gated_by_policy(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    allowed = root / "notes.md"
    metadata_only = root / "finance.md"
    denied = root / "secret.md"
    pdf = root / "paper.pdf"
    for path in (allowed, metadata_only, denied, pdf):
        path.write_text("placeholder", encoding="utf-8")

    engine = PolicyEngine(
        {
            "deny": {"paths": [str(denied)]},
            "metadata_only": {"paths": [str(metadata_only)]},
            "allow": {"paths": [str(root)]},
        }
    )
    result = scan_paths([root], engine)
    jobs = build_parse_jobs(result.entries)
    by_name = {job.path.name: job for job in jobs}

    assert "notes.md" in by_name
    assert by_name["notes.md"].parser == "direct_text"
    assert "paper.pdf" in by_name
    assert by_name["paper.pdf"].parser == "markitdown"
    assert "finance.md" not in by_name
    assert "secret.md" not in by_name
