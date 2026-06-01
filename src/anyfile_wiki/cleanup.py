from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import re

from .sidecars import attach_asset_ids


CLEANUP_PLAN_SCHEMA_VERSION = 1


def build_archive_plan(
    asset_records: Iterable[dict[str, Any]],
    collection_records: Iterable[dict[str, Any]],
    score_records: Iterable[dict[str, Any]],
    *,
    generated_at: str | None = None,
    min_duplicate_confidence: float = 0.7,
    min_archive_score: float = 0.55,
    max_delete_risk: float = 0.35,
    include_review_required: bool = False,
) -> list[dict[str, Any]]:
    """Build a reviewable cleanup plan from sidecar signals.

    The returned records are proposals only. They never represent filesystem
    actions that can be executed without a separate human-confirmed workflow.
    """
    now = generated_at or datetime.now(timezone.utc).isoformat()
    assets = attach_asset_ids(asset_records)
    assets_by_id = {str(record.get("asset_id")): record for record in assets}
    collections_by_id = {str(record.get("asset_id")): record for record in collection_records}
    scores_by_id = {str(record.get("asset_id")): record for record in score_records}

    plan: list[dict[str, Any]] = []
    for asset in assets:
        asset_id = str(asset.get("asset_id"))
        collection = collections_by_id.get(asset_id, {})
        score = scores_by_id.get(asset_id, {})
        decision = _cleanup_decision(
            asset,
            collection,
            score,
            min_duplicate_confidence=min_duplicate_confidence,
            min_archive_score=min_archive_score,
            max_delete_risk=max_delete_risk,
            include_review_required=include_review_required,
        )
        if decision is None:
            continue
        candidate_type, recommended_action = decision
        plan.append(
            _plan_record(
                asset,
                collection,
                score,
                assets_by_id,
                candidate_type=candidate_type,
                recommended_action=recommended_action,
                generated_at=now,
            )
        )
    return sorted(
        plan,
        key=lambda item: (
            -float(item.get("priority_score") or 0.0),
            str(item.get("candidate_type") or ""),
            _path_key(item.get("path")),
        ),
    )


def write_archive_plan_outputs(
    plan_records: Iterable[dict[str, Any]],
    output_dir: str | Path,
    *,
    asset_index_path: str | Path | None = None,
    collection_index_path: str | Path | None = None,
    asset_score_path: str | Path | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    records = list(plan_records)
    root = Path(output_dir)
    outputs = {
        "archive_plan_jsonl": root / "archive-plan.jsonl",
        "archive_plan_md": root / "archive-plan.md",
        "archive_plan_summary_json": root / "archive-plan-summary.json",
    }
    stats = archive_plan_stats(records)
    root.mkdir(parents=True, exist_ok=True)
    _write_jsonl(records, outputs["archive_plan_jsonl"])
    write_archive_plan_report(
        records,
        outputs["archive_plan_md"],
        stats=stats,
        asset_index_path=asset_index_path,
        collection_index_path=collection_index_path,
        asset_score_path=asset_score_path,
    )
    summary = {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "sources": {
            "asset_index": str(asset_index_path) if asset_index_path else "",
            "collection_index": str(collection_index_path) if collection_index_path else "",
            "asset_score": str(asset_score_path) if asset_score_path else "",
        },
        "outputs": {name: str(path) for name, path in outputs.items()},
        "safety": {
            "proposed_only": True,
            "executes_filesystem_actions": False,
            "requires_human_confirmation": True,
        },
    }
    outputs["archive_plan_summary_json"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return outputs, stats


def archive_plan_stats(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(records)
    by_type = Counter(str(record.get("candidate_type") or "unknown") for record in items)
    by_action = Counter(str(record.get("recommended_action") or "unknown") for record in items)
    by_policy = Counter(str(record.get("archive_policy") or "unknown") for record in items)
    return {
        "total_candidates": len(items),
        "duplicate_candidates": sum(1 for item in items if float(item.get("duplicate_confidence") or 0.0) >= 0.7),
        "archive_candidates": by_type.get("archive", 0),
        "delete_candidates": by_type.get("delete", 0),
        "review_first_candidates": by_type.get("review_first", 0),
        "requires_confirmation": sum(1 for item in items if bool(item.get("requires_confirmation"))),
        "by_candidate_type": dict(by_type),
        "by_recommended_action": dict(by_action),
        "by_archive_policy": dict(by_policy),
    }


def write_archive_plan_report(
    records: Iterable[dict[str, Any]],
    path: str | Path,
    *,
    stats: dict[str, Any] | None = None,
    asset_index_path: str | Path | None = None,
    collection_index_path: str | Path | None = None,
    asset_score_path: str | Path | None = None,
) -> None:
    items = list(records)
    summary = stats or archive_plan_stats(items)
    lines = [
        "# 安全清理候选计划",
        "",
        "本计划只整理索引层建议，不会移动、删除、重命名任何原始文件。",
        "所有候选都需要人工复核；如果未来执行真实文件动作，必须先生成独立回滚 manifest。",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
    ]
    if asset_index_path:
        lines.append(f"资产索引：`{asset_index_path}`")
    if collection_index_path:
        lines.append(f"资料族索引：`{collection_index_path}`")
    if asset_score_path:
        lines.append(f"评分索引：`{asset_score_path}`")
    lines.extend(
        [
            "",
            "## 概览",
            "",
            f"- 候选总数：{summary.get('total_candidates', 0)}",
            f"- 疑似重复信号：{summary.get('duplicate_candidates', 0)}",
            f"- 归档候选：{summary.get('archive_candidates', 0)}",
            f"- 删除复核候选：{summary.get('delete_candidates', 0)}",
            f"- 先复核候选：{summary.get('review_first_candidates', 0)}",
            "",
            "## 建议动作统计",
            "",
        ]
    )
    for action, count in sorted((summary.get("by_recommended_action") or {}).items()):
        lines.append(f"- `{action}`：{count}")
    if not items:
        lines.extend(["", "## 候选明细", "", "暂无候选。"])
    else:
        lines.extend(["", "## 候选明细", ""])
        for item in items:
            title = _text(item.get("title")) or _file_name(item.get("path")) or _text(item.get("asset_id"))
            lines.extend(
                [
                    f"### {title}",
                    "",
                    f"- 路径：`{_text(item.get('path'))}`",
                    f"- 候选类型：`{_text(item.get('candidate_type'))}`",
                    f"- 建议动作：`{_text(item.get('recommended_action'))}`",
                    f"- 真实文件操作：`{_text(item.get('proposed_operation'))}`",
                    f"- 归档策略：`{_text(item.get('archive_policy'))}`",
                    (
                        "- 分数："
                        f"archive={item.get('archive_score')}，"
                        f"retention={item.get('retention_score')}，"
                        f"delete_risk={item.get('delete_risk_score')}，"
                        f"duplicate={item.get('duplicate_confidence')}"
                    ),
                ]
            )
            virtual_path = _text(item.get("virtual_path"))
            if virtual_path:
                lines.append(f"- 虚拟路径：`{virtual_path}`")
            canonical_path = _text(item.get("canonical_path"))
            if canonical_path and canonical_path != _text(item.get("path")):
                lines.append(f"- 参考主文件：`{canonical_path}`")
            destination_hint = _text(item.get("destination_hint"))
            if destination_hint:
                lines.append(f"- 目标提示：`{destination_hint}`")
            reasons = _string_list(item.get("reasons"))
            if reasons:
                lines.append("- 原因：" + "；".join(reasons))
            lines.append(f"- 回滚要求：{_text(item.get('rollback_hint'))}")
            lines.append("")
    Path(path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _cleanup_decision(
    asset: dict[str, Any],
    collection: dict[str, Any],
    score: dict[str, Any],
    *,
    min_duplicate_confidence: float,
    min_archive_score: float,
    max_delete_risk: float,
    include_review_required: bool,
) -> tuple[str, str] | None:
    if _bool(asset.get("never_delete")) or _bool(score.get("never_delete")):
        return None
    review_required = (
        _bool(asset.get("needs_human_review"))
        or _bool(asset.get("review_requires_confirmation"))
        or _bool(collection.get("review_required"))
        or _text(score.get("archive_policy")) == "review"
    )
    if review_required:
        return ("review_first", "manual_review_before_cleanup") if include_review_required else None

    duplicate_confidence = _float(collection.get("duplicate_confidence"))
    archive_policy = _text(score.get("archive_policy"))
    archive_score = _float(score.get("archive_score"))
    delete_risk = _float(score.get("delete_risk_score"), default=1.0)

    if (
        duplicate_confidence >= min_duplicate_confidence
        and archive_policy == "delete_candidate"
        and delete_risk <= max_delete_risk
    ):
        return "delete", "review_delete_duplicate"
    if duplicate_confidence >= min_duplicate_confidence:
        return "duplicate", "review_duplicate_candidate"
    if archive_policy == "delete_candidate" and delete_risk <= max_delete_risk:
        return "delete", "review_delete_candidate"
    if archive_policy in {"nas", "cold"} and archive_score >= min_archive_score:
        return "archive", f"propose_{archive_policy}_archive"
    return None


def _plan_record(
    asset: dict[str, Any],
    collection: dict[str, Any],
    score: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]],
    *,
    candidate_type: str,
    recommended_action: str,
    generated_at: str,
) -> dict[str, Any]:
    asset_id = _text(asset.get("asset_id"))
    canonical_asset_id = _text(collection.get("canonical_asset_id"))
    canonical_asset = assets_by_id.get(canonical_asset_id, {})
    archive_score = _float(score.get("archive_score"))
    retention_score = _float(score.get("retention_score"))
    delete_risk_score = _float(score.get("delete_risk_score"), default=1.0)
    duplicate_confidence = _float(collection.get("duplicate_confidence"))
    priority = _priority_score(candidate_type, archive_score, delete_risk_score, duplicate_confidence)
    destination_hint = _destination_hint(candidate_type, recommended_action, asset, collection)
    reasons = _unique_strings(
        [
            *_string_list(score.get("score_reasons")),
            _text(collection.get("duplicate_reason")),
            _text(collection.get("merge_reason")),
            f"archive_policy:{_text(score.get('archive_policy'))}" if score.get("archive_policy") else "",
        ]
    )
    return {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "plan_id": _plan_id(asset_id, recommended_action),
        "asset_id": asset_id,
        "path": _text(asset.get("path")),
        "title": _text(asset.get("title")) or _file_name(asset.get("path")),
        "candidate_type": candidate_type,
        "recommended_action": recommended_action,
        "proposed_operation": "none",
        "safety_status": "proposed_only",
        "execution_allowed": False,
        "requires_confirmation": True,
        "rollback_manifest_required": True,
        "rollback_hint": "未来若执行真实移动/删除，必须先记录 original_path、target_path、action 和确认人。",
        "archive_policy": _text(score.get("archive_policy")),
        "usage_score": _float(score.get("usage_score")),
        "retention_score": retention_score,
        "archive_score": archive_score,
        "delete_risk_score": delete_risk_score,
        "duplicate_confidence": duplicate_confidence,
        "priority_score": priority,
        "reasons": reasons,
        "collection_id": _text(collection.get("collection_id")),
        "collection_title": _text(collection.get("collection_title")),
        "virtual_path": _text(collection.get("virtual_path")),
        "relation_type": _text(collection.get("relation_type")),
        "canonical_asset_id": canonical_asset_id,
        "canonical_path": _text(canonical_asset.get("path")),
        "destination_hint": destination_hint,
        "generated_at": generated_at,
    }


def _priority_score(candidate_type: str, archive_score: float, delete_risk_score: float, duplicate_confidence: float) -> float:
    score = archive_score * 0.4 + duplicate_confidence * 0.35 + (1.0 - delete_risk_score) * 0.25
    if candidate_type == "delete":
        score += 0.12
    elif candidate_type == "duplicate":
        score += 0.08
    return round(max(0.0, min(score, 1.0)), 2)


def _destination_hint(
    candidate_type: str,
    recommended_action: str,
    asset: dict[str, Any],
    collection: dict[str, Any],
) -> str:
    file_name = _file_name(asset.get("path")) or _text(asset.get("asset_id"))
    collection_title = _safe_segment(collection.get("collection_title")) or "uncategorized"
    if recommended_action == "propose_cold_archive":
        return f"cold-archive/{collection_title}/{file_name}"
    if recommended_action == "propose_nas_archive":
        return f"nas-archive/{collection_title}/{file_name}"
    if candidate_type == "duplicate":
        return f"manual-review/duplicates/{collection_title}/{file_name}"
    if candidate_type == "delete":
        return f"manual-review/delete-candidates/{collection_title}/{file_name}"
    if candidate_type == "review_first":
        return f"manual-review/needs-context/{collection_title}/{file_name}"
    return ""


def _plan_id(asset_id: str, recommended_action: str) -> str:
    digest = hashlib.sha256(f"{asset_id}|{recommended_action}".encode("utf-8")).hexdigest()
    return f"cleanup:plan-sha256:{digest}"


def _write_jsonl(records: list[dict[str, Any]], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    output.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def _safe_segment(value: Any) -> str:
    text = _text(value).strip() or "untitled"
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("._ ")[:80]


def _file_name(value: Any) -> str:
    path = _text(value).replace("\\", "/")
    return Path(path).name


def _path_key(value: Any) -> str:
    return _text(value).replace("\\", "/").casefold()


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_text(item).strip() for item in value if _text(item).strip()]
    text = _text(value).strip()
    return [text] if text else []


def _unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _text(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value)
