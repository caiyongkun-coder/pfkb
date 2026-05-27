from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .scan import ScanEntry


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".log",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".scss",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}


@dataclass(frozen=True)
class ParseJob:
    path: Path
    parser: str
    reason: str
    embedding_allowed: bool


def build_parse_jobs(entries: list[ScanEntry]) -> list[ParseJob]:
    """Build parser jobs only for entries whose policy allows content reads."""

    jobs: list[ParseJob] = []
    for entry in entries:
        decision = entry.decision
        if entry.is_dir or not decision.is_read_allowed or not decision.is_extract_allowed:
            continue
        parser = choose_parser(entry.extension)
        if parser is None:
            continue
        jobs.append(
            ParseJob(
                path=Path(entry.path),
                parser=parser,
                reason=f"{decision.access_policy}: {decision.reason}",
                embedding_allowed=decision.is_embedding_allowed,
            )
        )
    return jobs


def choose_parser(extension: str) -> str | None:
    normalized = extension.lower()
    if normalized in TEXT_EXTENSIONS:
        return "direct_text"
    if normalized in {".pdf", ".docx", ".pptx", ".xlsx"}:
        return "markitdown"
    return None
