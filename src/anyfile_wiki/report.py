from __future__ import annotations

from collections import Counter
from pathlib import Path
import json

from .scan import ScanEntry, ScanResult


def summarize_by_policy(entries: list[ScanEntry]) -> dict[str, int]:
    return dict(Counter(entry.decision.access_policy for entry in entries))


def summarize_by_source(entries: list[ScanEntry], *, limit: int = 20) -> list[tuple[str, int]]:
    counter = Counter(entry.decision.policy_source for entry in entries)
    return counter.most_common(limit)


def write_scan_plan(result: ScanResult, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AnyFile Wiki Dry-run Scan Plan",
        "",
        "Generated before content extraction. This report records path-level access decisions only.",
        "",
        "## Summary",
        "",
    ]
    for key, value in result.stats.as_dict().items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Policy Counts", ""])
    for policy, count in sorted(summarize_by_policy(result.entries).items()):
        lines.append(f"- `{policy}`: {count}")

    lines.extend(["", "## Top Policy Sources", ""])
    for source, count in summarize_by_source(result.entries):
        lines.append(f"- `{source}`: {count}")

    if result.errors:
        lines.extend(["", "## Errors", ""])
        for error in result.errors:
            lines.append(f"- {error}")

    lines.extend(["", "## Entries", ""])
    lines.append("| Policy | Type | Path | Reason |")
    lines.append("| --- | --- | --- | --- |")
    for entry in result.entries:
        kind = "dir" if entry.is_dir else "file"
        decision = entry.decision
        lines.append(
            f"| `{decision.access_policy}` | {kind} | `{entry.path}` | {decision.policy_source}: {decision.reason} |"
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_access_log(result: ScanResult, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for entry in result.entries:
            payload = {
                "path": entry.path,
                "name": entry.name,
                "extension": entry.extension,
                "is_dir": entry.is_dir,
                "exists_now": entry.exists_now,
                "size_bytes": entry.size_bytes,
                "mtime": entry.mtime,
                "ctime": entry.ctime,
                "last_seen_at": entry.last_seen_at,
                "decision": entry.decision.as_dict(),
                "extra": entry.extra,
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
