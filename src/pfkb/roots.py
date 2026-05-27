from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class CandidateRoot:
    name: str
    path: Path
    exists: bool
    source: str


def discover_candidate_roots(*, existing_only: bool = True) -> list[CandidateRoot]:
    home = Path.home()
    candidates = [
        CandidateRoot("home", home, home.exists(), "Path.home"),
        CandidateRoot("desktop", home / "Desktop", (home / "Desktop").exists(), "standard"),
        CandidateRoot("documents", home / "Documents", (home / "Documents").exists(), "standard"),
        CandidateRoot("downloads", home / "Downloads", (home / "Downloads").exists(), "standard"),
    ]

    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        raw = os.environ.get(env_name)
        if raw:
            path = Path(raw)
            candidates.append(CandidateRoot(env_name.lower(), path, path.exists(), f"env:{env_name}"))

    seen: set[str] = set()
    result: list[CandidateRoot] = []
    for candidate in candidates:
        key = str(candidate.path).lower()
        if key in seen:
            continue
        seen.add(key)
        if existing_only and not candidate.exists:
            continue
        result.append(candidate)
    return result
