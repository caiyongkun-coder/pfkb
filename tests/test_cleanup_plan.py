from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from anyfile_wiki.cleanup import build_archive_plan, write_archive_plan_outputs
from anyfile_wiki.cli import main as cli_main
from anyfile_wiki.sidecars import attach_asset_ids, write_sidecar_outputs


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


def _asset(path: str, output_path: str, **overrides) -> dict:
    record = {
        "path": path,
        "output_path": output_path,
        "status": "ok",
        "title": Path(path).name,
        "summary": f"{Path(path).name} summary",
        "tags": ["document"],
        "primary_tag": "document",
        "content_type": "document",
        "extension": Path(path).suffix,
        "parser": "direct_text",
        "embedding_allowed": True,
        "char_count": 80,
        "word_count": 20,
        "line_count": 3,
        "analyzed_at": "2026-05-28T00:00:00+00:00",
        "source_extract_status": "ok",
        "analysis_method": "rules",
        "confidence": 0.05,
        "needs_human_review": False,
        "review_reason": "",
        "rule_title": Path(path).name,
        "rule_summary": "rule summary",
        "rule_tags": ["document"],
        "key_points": [],
        "model_notes": "",
        "error": "",
    }
    record.update(overrides)
    return record


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_archive_plan_builds_proposed_only_duplicate_delete_candidate(tmp_path):
    text_path = tmp_path / "extract" / "budget.md"
    text_path.parent.mkdir(parents=True)
    text_path.write_text("same extracted budget text", encoding="utf-8")
    assets = attach_asset_ids(
        [
            _asset("C:/docs/Budget.xlsx", str(text_path)),
            _asset("C:/docs/Budget copy.xlsx", str(text_path)),
        ]
    )
    outputs, _stats = write_sidecar_outputs(assets, tmp_path / "assets")
    collections = _read_jsonl(outputs["collection_index_jsonl"])
    scores = _read_jsonl(outputs["asset_score_jsonl"])

    plan = build_archive_plan(
        assets,
        collections,
        scores,
        generated_at="2026-06-01T00:00:00+00:00",
    )

    assert len(plan) == 1
    candidate = plan[0]
    assert candidate["path"] == "C:/docs/Budget copy.xlsx"
    assert candidate["candidate_type"] == "duplicate"
    assert candidate["recommended_action"] == "review_duplicate_candidate"
    assert candidate["proposed_operation"] == "none"
    assert candidate["execution_allowed"] is False
    assert candidate["requires_confirmation"] is True
    assert candidate["rollback_manifest_required"] is True
    assert candidate["duplicate_confidence"] == 0.95
    assert candidate["canonical_path"] == "C:/docs/Budget.xlsx"


def test_archive_plan_outputs_manifest_report_and_summary(tmp_path):
    plan = [
        {
            "schema_version": 1,
            "plan_id": "cleanup:plan-sha256:test",
            "asset_id": "asset:path-sha256:test",
            "path": "C:/docs/old.zip",
            "title": "old.zip",
            "candidate_type": "archive",
            "recommended_action": "propose_cold_archive",
            "proposed_operation": "none",
            "safety_status": "proposed_only",
            "execution_allowed": False,
            "requires_confirmation": True,
            "rollback_manifest_required": True,
            "rollback_hint": "未来若执行真实移动/删除，必须先记录 original_path、target_path、action 和确认人。",
            "archive_policy": "cold",
            "usage_score": 0.0,
            "retention_score": 0.2,
            "archive_score": 0.8,
            "delete_risk_score": 0.4,
            "duplicate_confidence": 0.0,
            "priority_score": 0.47,
            "reasons": ["low_retention"],
            "collection_id": "collection:test",
            "collection_title": "old",
            "virtual_path": "09_压缩包_不可解析_待复核/old",
            "relation_type": "master",
            "canonical_asset_id": "asset:path-sha256:test",
            "canonical_path": "C:/docs/old.zip",
            "destination_hint": "cold-archive/old/old.zip",
            "generated_at": "2026-06-01T00:00:00+00:00",
        }
    ]

    outputs, stats = write_archive_plan_outputs(plan, tmp_path / "cleanup", asset_index_path="asset-index.jsonl")

    assert stats["total_candidates"] == 1
    assert outputs["archive_plan_jsonl"].exists()
    assert outputs["archive_plan_md"].exists()
    assert outputs["archive_plan_summary_json"].exists()
    record = json.loads(outputs["archive_plan_jsonl"].read_text(encoding="utf-8").splitlines()[0])
    assert record["proposed_operation"] == "none"
    markdown = outputs["archive_plan_md"].read_text(encoding="utf-8")
    assert "不会移动、删除、重命名任何原始文件" in markdown
    summary = json.loads(outputs["archive_plan_summary_json"].read_text(encoding="utf-8"))
    assert summary["safety"]["executes_filesystem_actions"] is False


def test_archive_plan_cli_reads_sidecars_and_writes_outputs(tmp_path):
    text_path = tmp_path / "extract" / "budget.md"
    text_path.parent.mkdir(parents=True)
    text_path.write_text("same extracted budget text", encoding="utf-8")
    assets = attach_asset_ids(
        [
            _asset("C:/docs/Budget.xlsx", str(text_path)),
            _asset("C:/docs/Budget copy.xlsx", str(text_path)),
        ]
    )
    asset_dir = tmp_path / "assets"
    asset_index = asset_dir / "asset-index.jsonl"
    _write_jsonl(asset_index, assets)
    write_sidecar_outputs(assets, asset_dir, asset_index_path=asset_index)

    code, stdout, stderr = _run_cli(
        [
            "archive-plan",
            "--asset-index",
            str(asset_index),
            "--out",
            str(tmp_path / "cleanup"),
            "--json",
        ]
    )

    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["records"] == 1
    assert payload["safety"]["proposed_only"] is True
    assert Path(payload["outputs"]["archive_plan_jsonl"]).exists()
    assert Path(payload["outputs"]["archive_plan_md"]).exists()
