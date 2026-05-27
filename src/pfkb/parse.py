from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re

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
    source_policy: str = "allow"
    source_size_bytes: int | None = None
    source_mtime: float | None = None


@dataclass(frozen=True)
class ExtractResult:
    path: str
    parser: str
    status: str
    output_path: str | None
    error: str | None
    embedding_allowed: bool
    created_at: str
    source_size_bytes: int | None = None
    source_mtime: float | None = None
    output_sha256: str | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class ExtractPlan:
    jobs: list[ParseJob]
    skipped: list[ExtractResult]


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
                source_policy=decision.access_policy,
                source_size_bytes=entry.size_bytes,
                source_mtime=entry.mtime,
            )
        )
    return jobs


def build_parse_jobs_from_records(records: list[dict]) -> list[ParseJob]:
    return plan_parse_jobs_from_records(records).jobs


def plan_parse_jobs_from_records(
    records: list[dict],
    *,
    latest_success_by_path: dict[str, dict] | None = None,
    latest_by_path: dict[str, dict] | None = None,
    force: bool = False,
    retry_failed: bool = False,
) -> ExtractPlan:
    latest_success_by_path = latest_success_by_path or {}
    latest_by_path = latest_by_path or {}
    jobs: list[ParseJob] = []
    skipped: list[ExtractResult] = []
    for record in records:
        if record.get("is_dir"):
            continue
        if not record.get("is_read_allowed") or not record.get("is_extract_allowed"):
            continue
        parser = choose_parser(str(record.get("extension", "")))
        if parser is None:
            continue
        job = ParseJob(
            path=Path(str(record["path"])),
            parser=parser,
            reason=f"{record.get('access_policy')}: {record.get('policy_reason', '')}",
            embedding_allowed=bool(record.get("is_embedding_allowed")),
            source_policy=str(record.get("access_policy", "allow")),
            source_size_bytes=_optional_int(record.get("size_bytes")),
            source_mtime=_optional_float(record.get("mtime")),
        )
        latest = latest_by_path.get(str(job.path))
        latest_success = latest_success_by_path.get(str(job.path))

        if retry_failed:
            if latest and latest.get("status") in {"error", "skipped"}:
                jobs.append(job)
            else:
                skipped.append(_skip_result(job, latest_success, "retry_failed filter"))
            continue

        if force:
            jobs.append(job)
            continue

        if latest_success and _same_source(job, latest_success):
            skipped.append(_skip_result(job, latest_success, "source unchanged"))
            continue

        jobs.append(job)
    return ExtractPlan(jobs=jobs, skipped=skipped)


def choose_parser(extension: str) -> str | None:
    normalized = extension.lower()
    if normalized in TEXT_EXTENSIONS:
        return "direct_text"
    if normalized in {".pdf", ".docx", ".pptx", ".xlsx"}:
        return "markitdown"
    return None


def extract_jobs(jobs: list[ParseJob], output_dir: str | Path) -> list[ExtractResult]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    results: list[ExtractResult] = []
    for job in jobs:
        if job.parser == "direct_text":
            results.append(_extract_direct_text(job, root))
        elif job.parser == "markitdown":
            results.append(_extract_markitdown(job, root))
        else:
            results.append(_result(job, "skipped", None, f"unsupported parser: {job.parser}"))
    return results


def write_manifest(results: list[ExtractResult], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n")


def _extract_direct_text(job: ParseJob, output_dir: Path) -> ExtractResult:
    try:
        text = _read_text(job.path)
        output = output_dir / "text" / _artifact_name(job.path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        return _result(job, "ok", output, None)
    except Exception as exc:  # noqa: BLE001 - manifest should capture parser failures.
        return _result(job, "error", None, str(exc))


def _extract_markitdown(job: ParseJob, output_dir: Path) -> ExtractResult:
    try:
        from markitdown import MarkItDown  # type: ignore
    except Exception as exc:  # noqa: BLE001 - optional dependency.
        return _result(job, "skipped", None, f"markitdown unavailable: {exc}")

    try:
        converter = MarkItDown()
        converted = converter.convert(str(job.path))
        text = getattr(converted, "text_content", None)
        if text is None:
            text = str(converted)
        output = output_dir / "markitdown" / _artifact_name(job.path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        return _result(job, "ok", output, None)
    except Exception as exc:  # noqa: BLE001 - manifest should capture parser failures.
        return _result(job, "error", None, str(exc))


def _result(job: ParseJob, status: str, output_path: Path | None, error: str | None) -> ExtractResult:
    return ExtractResult(
        path=str(job.path),
        parser=job.parser,
        status=status,
        output_path=str(output_path) if output_path else None,
        error=error,
        embedding_allowed=job.embedding_allowed,
        created_at=datetime.now(timezone.utc).isoformat(),
        source_size_bytes=job.source_size_bytes,
        source_mtime=job.source_mtime,
        output_sha256=_sha256_file(output_path) if output_path and output_path.exists() else None,
    )


def _skip_result(job: ParseJob, latest_success: dict | None, reason: str) -> ExtractResult:
    return ExtractResult(
        path=str(job.path),
        parser=job.parser,
        status="up_to_date",
        output_path=str(latest_success.get("output_path")) if latest_success and latest_success.get("output_path") else None,
        error=None,
        embedding_allowed=job.embedding_allowed,
        created_at=datetime.now(timezone.utc).isoformat(),
        source_size_bytes=job.source_size_bytes,
        source_mtime=job.source_mtime,
        output_sha256=str(latest_success.get("output_sha256")) if latest_success and latest_success.get("output_sha256") else None,
        skip_reason=reason,
    )


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return _normalize_newlines(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _normalize_newlines(data.decode("utf-8", errors="replace"))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _artifact_name(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "file"
    return f"{digest}-{stem}.md"


def _same_source(job: ParseJob, latest: dict) -> bool:
    return (
        latest.get("parser") == job.parser
        and _optional_int(latest.get("source_size_bytes")) == job.source_size_bytes
        and _optional_float(latest.get("source_mtime")) == job.source_mtime
        and bool(latest.get("output_path"))
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_int(value) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value) -> float | None:
    if value is None:
        return None
    return float(value)
