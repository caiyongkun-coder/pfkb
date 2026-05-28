from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


VALID_DECISIONS = {
    "confirm_current",
    "allow_local_llm",
    "allow_cloud_llm",
    "mark_manual",
    "ignore",
    "later",
    "keep_private",
}


@dataclass(frozen=True)
class ReviewDecision:
    path: str
    decision: str
    category: str = ""
    severity: str = ""
    manual_tags: tuple[str, ...] = ()
    note: str = ""
    decided_at: str = ""
    source_reason: str = ""
    source_action: str = ""


@dataclass(frozen=True)
class DecisionAction:
    path: str
    action: str
    source_decision: str
    category: str = ""
    severity: str = ""
    manual_tags: tuple[str, ...] = ()
    note: str = ""
    privacy_level: str = "local"
    requires_confirmation: bool = False
    reason: str = ""
    next_step: str = ""
    decided_at: str = ""


_ACTION_TITLES = {
    "accept_current_analysis": "确认当前分析结果",
    "queue_local_llm_review": "加入本地 LLM 复核队列",
    "propose_cloud_llm_authorization": "生成云端 LLM 授权候选",
    "apply_manual_metadata": "应用人工整理结果",
    "record_manual_tags": "记录人工标签覆盖",
    "add_to_ignore_candidates": "加入忽略候选清单",
    "defer_review": "稍后继续复核",
    "keep_private_metadata_only": "保持隐私保护",
}


def load_review_decisions(path: str | Path) -> list[ReviewDecision]:
    source = Path(path)
    decisions: list[ReviewDecision] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc}") from exc
        decisions.append(_coerce_decision(payload, line_number=line_number))
    return decisions


def decision_stats(decisions: list[ReviewDecision]) -> dict[str, dict[str, int]]:
    return {
        "by_decision": dict(Counter(decision.decision for decision in decisions).most_common()),
        "by_category": dict(Counter(decision.category or "unknown" for decision in decisions).most_common()),
        "by_severity": dict(Counter(decision.severity or "unknown" for decision in decisions).most_common()),
    }


def decisions_as_dicts(decisions: list[ReviewDecision]) -> list[dict[str, Any]]:
    return [
        {
            "path": decision.path,
            "decision": decision.decision,
            "category": decision.category,
            "severity": decision.severity,
            "manual_tags": list(decision.manual_tags),
            "note": decision.note,
            "decided_at": decision.decided_at,
            "source_reason": decision.source_reason,
            "source_action": decision.source_action,
        }
        for decision in decisions
    ]


def build_decision_actions(decisions: list[ReviewDecision]) -> list[DecisionAction]:
    actions: list[DecisionAction] = []
    for decision in decisions:
        primary = _decision_to_primary_action(decision)
        actions.append(primary)
        if decision.manual_tags and decision.decision != "mark_manual":
            actions.append(
                DecisionAction(
                    path=decision.path,
                    action="record_manual_tags",
                    source_decision=decision.decision,
                    category=decision.category,
                    severity=decision.severity,
                    manual_tags=decision.manual_tags,
                    note=decision.note,
                    privacy_level="local_metadata",
                    reason="人类在批复时补充了标签，需要后续写入知识索引或标签覆盖记录。",
                    next_step="把 manual_tags 作为人工标签覆盖记录保存；不要因此扩大文件读取权限。",
                    decided_at=decision.decided_at,
                )
            )
    return actions


def decision_action_stats(actions: list[DecisionAction]) -> dict[str, dict[str, int]]:
    return {
        "by_action": dict(Counter(action.action for action in actions).most_common()),
        "by_privacy_level": dict(Counter(action.privacy_level or "unknown" for action in actions).most_common()),
        "requires_confirmation": dict(
            Counter("yes" if action.requires_confirmation else "no" for action in actions).most_common()
        ),
    }


def actions_as_dicts(actions: list[DecisionAction]) -> list[dict[str, Any]]:
    return [
        {
            "path": action.path,
            "action": action.action,
            "title": _ACTION_TITLES.get(action.action, action.action),
            "source_decision": action.source_decision,
            "category": action.category,
            "severity": action.severity,
            "manual_tags": list(action.manual_tags),
            "note": action.note,
            "privacy_level": action.privacy_level,
            "requires_confirmation": action.requires_confirmation,
            "reason": action.reason,
            "next_step": action.next_step,
            "decided_at": action.decided_at,
        }
        for action in actions
    ]


def format_decisions_summary(decisions: list[ReviewDecision]) -> str:
    stats = decision_stats(decisions)
    lines = [
        "review_decisions:",
        f"- total: {len(decisions)}",
    ]
    lines.append("by_decision:")
    _append_counts(lines, stats["by_decision"])
    lines.append("by_category:")
    _append_counts(lines, stats["by_category"])
    lines.append("by_severity:")
    _append_counts(lines, stats["by_severity"])
    return "\n".join(lines)


def format_action_plan_summary(actions: list[DecisionAction]) -> str:
    stats = decision_action_stats(actions)
    lines = [
        "decision_actions:",
        f"- total: {len(actions)}",
    ]
    lines.append("by_action:")
    _append_counts(lines, stats["by_action"])
    lines.append("by_privacy_level:")
    _append_counts(lines, stats["by_privacy_level"])
    lines.append("requires_confirmation:")
    _append_counts(lines, stats["requires_confirmation"])
    return "\n".join(lines)


def write_decisions_summary_md(decisions: list[ReviewDecision], path: str | Path) -> None:
    stats = decision_stats(decisions)
    lines = [
        "# 人工批复结果摘要",
        "",
        "本文件由 `anyfile-wiki decisions` 读取 `review-decisions.jsonl` 后生成。",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        "",
        f"- 批复总数：{len(decisions)}",
        "",
        "## 按批复动作统计",
        "",
    ]
    lines.extend(_md_counts(stats["by_decision"]))
    lines.extend(["", "## 按复核类别统计", ""])
    lines.extend(_md_counts(stats["by_category"]))
    lines.extend(["", "## 批复明细", ""])
    for decision in decisions:
        lines.extend(
            [
                f"### {Path(decision.path).name or decision.path}",
                "",
                f"- 路径：`{decision.path}`",
                f"- 批复动作：`{decision.decision}`",
                f"- 复核类别：`{decision.category or 'unknown'}`",
                f"- 优先级：`{decision.severity or 'unknown'}`",
            ]
        )
        if decision.manual_tags:
            lines.append("- 人工标签：" + " ".join(f"`{tag}`" for tag in decision.manual_tags))
        if decision.note:
            lines.append(f"- 备注：{decision.note}")
        lines.append("")
    Path(path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_next_actions_jsonl(actions: list[DecisionAction], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in actions_as_dicts(actions)]
    output.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def write_decision_plan_md(actions: list[DecisionAction], path: str | Path) -> None:
    stats = decision_action_stats(actions)
    lines = [
        "# 人工批复后续执行计划",
        "",
        "本文件由 `anyfile-wiki decisions` 读取 `review-decisions.jsonl` 后生成，供 agent 决定下一轮处理动作。",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        "",
        f"- 后续动作总数：{len(actions)}",
        f"- 需要再次确认：{stats['requires_confirmation'].get('yes', 0)}",
        "",
        "## 执行原则",
        "",
        "- 这是计划文件，不会直接移动、删除、重命名源文件，也不会直接修改隐私配置。",
        "- `allow_cloud_llm` 只会生成云端授权候选；没有显式配置授权路径和风险确认前，agent 不应调用云端模型。",
        "- 人工标签只应作为标签覆盖或补充记录保存，不应自动扩大文件读取权限。",
        "",
        "## 按动作统计",
        "",
    ]
    lines.extend(_md_counts(stats["by_action"]))
    lines.extend(["", "## 按隐私级别统计", ""])
    lines.extend(_md_counts(stats["by_privacy_level"]))
    lines.extend(["", "## 后续动作明细", ""])
    for index, action in enumerate(actions, start=1):
        lines.extend(
            [
                f"### {index}. {Path(action.path).name or action.path}",
                "",
                f"- 路径：`{action.path}`",
                f"- 后续动作：`{action.action}`（{_ACTION_TITLES.get(action.action, action.action)}）",
                f"- 来源批复：`{action.source_decision}`",
                f"- 复核类别：`{action.category or 'unknown'}`",
                f"- 优先级：`{action.severity or 'unknown'}`",
                f"- 隐私级别：`{action.privacy_level}`",
                f"- 需要再次确认：{'是' if action.requires_confirmation else '否'}",
                f"- 原因：{action.reason}",
                f"- 下一步：{action.next_step}",
            ]
        )
        if action.manual_tags:
            lines.append("- 人工标签：" + " ".join(f"`{tag}`" for tag in action.manual_tags))
        if action.note:
            lines.append(f"- 备注：{action.note}")
        lines.append("")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _coerce_decision(payload: dict[str, Any], *, line_number: int) -> ReviewDecision:
    if not isinstance(payload, dict):
        raise ValueError(f"line {line_number}: decision record must be an object")
    path = str(payload.get("path") or "").strip()
    if not path:
        raise ValueError(f"line {line_number}: missing path")
    decision = str(payload.get("decision") or "").strip()
    if decision not in VALID_DECISIONS:
        valid = ", ".join(sorted(VALID_DECISIONS))
        raise ValueError(f"line {line_number}: unsupported decision {decision!r}; expected one of {valid}")
    manual_tags = payload.get("manual_tags") or payload.get("tags") or []
    if not isinstance(manual_tags, list):
        manual_tags = [manual_tags]
    return ReviewDecision(
        path=path,
        decision=decision,
        category=str(payload.get("category") or ""),
        severity=str(payload.get("severity") or ""),
        manual_tags=tuple(str(tag) for tag in manual_tags if str(tag)),
        note=str(payload.get("note") or ""),
        decided_at=str(payload.get("decided_at") or ""),
        source_reason=str(payload.get("source_reason") or ""),
        source_action=str(payload.get("source_action") or ""),
    )


def _decision_to_primary_action(decision: ReviewDecision) -> DecisionAction:
    common = {
        "path": decision.path,
        "source_decision": decision.decision,
        "category": decision.category,
        "severity": decision.severity,
        "manual_tags": decision.manual_tags,
        "note": decision.note,
        "decided_at": decision.decided_at,
    }
    if decision.decision == "confirm_current":
        return DecisionAction(
            **common,
            action="accept_current_analysis",
            privacy_level="local_metadata",
            reason="人类确认当前分析结果可接受。",
            next_step="保留当前摘要、标签和复核状态，并让后续知识索引优先采用该结果。",
        )
    if decision.decision == "allow_local_llm":
        return DecisionAction(
            **common,
            action="queue_local_llm_review",
            privacy_level="local_content",
            reason="人类允许本地模型读取该文件的提取文本进行语义复核。",
            next_step="在隐私策略和 LLM 配置仍然允许的前提下，把该文件加入本地 LLM 分析队列。",
        )
    if decision.decision == "allow_cloud_llm":
        return DecisionAction(
            **common,
            action="propose_cloud_llm_authorization",
            privacy_level="cloud_candidate",
            requires_confirmation=True,
            reason="人类在复核页表达了云端 LLM 候选意向，但云端读取仍需要显式路径授权和风险确认。",
            next_step="生成配置变更建议或待确认清单；只有 configs/llm.yaml 已授权路径后，才允许进入云端 LLM 队列。",
        )
    if decision.decision == "mark_manual":
        return DecisionAction(
            **common,
            action="apply_manual_metadata",
            privacy_level="local_metadata",
            reason="人类已经手动整理该文件，系统应记录人工结果。",
            next_step="把备注和 manual_tags 写入人工整理记录，并在知识索引中标记为已人工复核。",
        )
    if decision.decision == "ignore":
        return DecisionAction(
            **common,
            action="add_to_ignore_candidates",
            privacy_level="local_metadata",
            requires_confirmation=True,
            reason="人类希望忽略该文件；这应先成为忽略候选，避免误伤重要资产。",
            next_step="生成忽略候选清单，等待 agent 或用户确认后再建议调整 excludes/privacy 配置。",
        )
    if decision.decision == "later":
        return DecisionAction(
            **common,
            action="defer_review",
            privacy_level="local_metadata",
            reason="人类选择稍后处理。",
            next_step="保留在待复核队列，降低本轮处理优先级，并在后续 review 页面继续展示。",
        )
    return DecisionAction(
        **common,
        action="keep_private_metadata_only",
        privacy_level="private",
        reason="人类要求保持隐私，不扩大读取或模型处理权限。",
        next_step="保持当前隐私策略；后续只保留必要元数据，不加入 LLM 复核队列。",
    )


def _append_counts(lines: list[str], counts: dict[str, int]) -> None:
    if not counts:
        lines.append("- empty: 0")
        return
    for key, count in counts.items():
        lines.append(f"- {key}: {count}")


def _md_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["- empty：0"]
    return [f"- `{key}`：{count}" for key, count in counts.items()]
