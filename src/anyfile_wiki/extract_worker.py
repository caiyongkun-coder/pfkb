from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .parse import ParseJob, _extract_direct_text, _extract_markitdown, _extract_ocr, _extract_spreadsheet


def main() -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run one extraction job in an isolated worker process.")
    parser.add_argument("--path", required=True)
    parser.add_argument("--parser", required=True, choices=("direct_text", "markitdown", "spreadsheet", "ocr"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--embedding-allowed", choices=("0", "1"), default="1")
    parser.add_argument("--source-policy", default="allow")
    parser.add_argument("--source-size-bytes", default="")
    parser.add_argument("--source-mtime", default="")
    args = parser.parse_args()

    job = ParseJob(
        path=Path(args.path),
        parser=args.parser,
        reason=f"{args.source_policy}: worker extraction",
        embedding_allowed=args.embedding_allowed == "1",
        source_policy=args.source_policy,
        source_size_bytes=_optional_int(args.source_size_bytes),
        source_mtime=_optional_float(args.source_mtime),
    )

    with redirect_stdout(sys.stderr):
        if job.parser == "direct_text":
            result = _extract_direct_text(job, Path(args.out))
        elif job.parser == "markitdown":
            result = _extract_markitdown(job, Path(args.out))
        elif job.parser == "spreadsheet":
            result = _extract_spreadsheet(job, Path(args.out))
        else:
            result = _extract_ocr(job, Path(args.out))

    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


def _optional_int(value: str) -> int | None:
    if not value:
        return None
    return int(value)


def _optional_float(value: str) -> float | None:
    if not value:
        return None
    return float(value)


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
