from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import fnmatch
import os

import yaml


POLICY_DENY = "deny"
POLICY_METADATA_ONLY = "metadata_only"
POLICY_NO_EMBEDDING = "no_embedding"
POLICY_ALLOW = "allow"


@dataclass(frozen=True)
class AccessDecision:
    path: str
    is_dir: bool
    access_policy: str
    policy_source: str
    reason: str
    is_read_allowed: bool
    is_extract_allowed: bool
    is_index_allowed: bool
    is_embedding_allowed: bool
    metadata_only: bool
    is_excluded: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "is_dir": self.is_dir,
            "access_policy": self.access_policy,
            "policy_source": self.policy_source,
            "reason": self.reason,
            "is_read_allowed": self.is_read_allowed,
            "is_extract_allowed": self.is_extract_allowed,
            "is_index_allowed": self.is_index_allowed,
            "is_embedding_allowed": self.is_embedding_allowed,
            "metadata_only": self.metadata_only,
            "is_excluded": self.is_excluded,
        }


@dataclass(frozen=True)
class RuleMatch:
    policy: str
    source: str
    reason: str


def load_policy(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    return _load_yaml(path)


def load_excludes(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if path is None:
        default_path = Path(__file__).resolve().parents[2] / "configs" / "excludes.default.yaml"
        if default_path.exists():
            return _load_yaml(default_path)
    return _load_yaml(path)


def _load_yaml(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if path is None:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8-sig") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config must be a mapping: {config_path}")
    return loaded


class PolicyEngine:
    """Decides whether scanner may read, extract, or index a path.

    The engine is intentionally path-first. It can decide on metadata from the
    path and directory entry before any file content is opened.
    """

    def __init__(
        self,
        privacy: dict[str, Any] | None = None,
        excludes: dict[str, Any] | None = None,
        *,
        require_allow: bool | None = None,
        policy: dict[str, Any] | None = None,
        default_excludes: dict[str, Any] | None = None,
    ) -> None:
        self.privacy = privacy or policy or {}
        self.excludes = excludes or default_excludes or {}
        configured_require_allow = self.privacy.get("require_allow")
        self.require_allow = bool(configured_require_allow if require_allow is None else require_allow)

    @classmethod
    def from_files(
        cls,
        privacy_path: str | os.PathLike[str] | None = None,
        excludes_path: str | os.PathLike[str] | None = None,
    ) -> "PolicyEngine":
        return cls(load_policy(privacy_path), load_excludes(excludes_path))

    def decide(self, path: str | os.PathLike[str], *, is_dir: bool = False) -> AccessDecision:
        raw_path = str(path)
        normalized = normalize_path(raw_path)
        extension = Path(raw_path).suffix.lower()
        name = Path(raw_path).name.lower()

        for match in self._matches_for_policy(POLICY_DENY, normalized, name, extension, is_dir):
            return self._decision(normalized, is_dir, match)

        exclude_match = self._match_excludes(normalized, name, extension, is_dir)
        if exclude_match:
            return self._decision(normalized, is_dir, exclude_match)

        for match in self._matches_for_policy(POLICY_METADATA_ONLY, normalized, name, extension, is_dir):
            return self._decision(normalized, is_dir, match)

        for match in self._matches_for_policy(POLICY_NO_EMBEDDING, normalized, name, extension, is_dir):
            return self._decision(normalized, is_dir, match)

        allow_match = next(
            iter(self._matches_for_policy(POLICY_ALLOW, normalized, name, extension, is_dir)),
            None,
        )
        if allow_match:
            return self._decision(normalized, is_dir, allow_match)

        if self.require_allow:
            return self._decision(
                normalized,
                is_dir,
                RuleMatch(POLICY_DENY, "privacy.require_allow", "No allow rule matched"),
            )

        return self._decision(
            normalized,
            is_dir,
            RuleMatch(POLICY_ALLOW, "default", "No deny or restrictive rule matched"),
        )

    def _decision(self, path: str, is_dir: bool, match: RuleMatch) -> AccessDecision:
        if match.policy == POLICY_DENY:
            return AccessDecision(
                path=path,
                is_dir=is_dir,
                access_policy=POLICY_DENY,
                policy_source=match.source,
                reason=match.reason,
                is_read_allowed=False,
                is_extract_allowed=False,
                is_index_allowed=False,
                is_embedding_allowed=False,
                metadata_only=False,
                is_excluded=True,
            )
        if match.policy == POLICY_METADATA_ONLY:
            return AccessDecision(
                path=path,
                is_dir=is_dir,
                access_policy=POLICY_METADATA_ONLY,
                policy_source=match.source,
                reason=match.reason,
                is_read_allowed=False,
                is_extract_allowed=False,
                is_index_allowed=False,
                is_embedding_allowed=False,
                metadata_only=True,
                is_excluded=False,
            )
        if match.policy == POLICY_NO_EMBEDDING:
            return AccessDecision(
                path=path,
                is_dir=is_dir,
                access_policy=POLICY_NO_EMBEDDING,
                policy_source=match.source,
                reason=match.reason,
                is_read_allowed=True,
                is_extract_allowed=True,
                is_index_allowed=True,
                is_embedding_allowed=False,
                metadata_only=False,
                is_excluded=False,
            )
        return AccessDecision(
            path=path,
            is_dir=is_dir,
            access_policy=POLICY_ALLOW,
            policy_source=match.source,
            reason=match.reason,
            is_read_allowed=True,
            is_extract_allowed=True,
            is_index_allowed=True,
            is_embedding_allowed=True,
            metadata_only=False,
            is_excluded=False,
        )

    def _matches_for_policy(
        self,
        policy: str,
        normalized: str,
        name: str,
        extension: str,
        is_dir: bool,
    ) -> Iterable[RuleMatch]:
        section = _as_mapping(self.privacy.get(policy))
        yield from self._matches_section(
            section,
            normalized,
            name,
            extension,
            is_dir,
            policy=policy,
            source=f"privacy.{policy}",
        )

    def _match_excludes(
        self,
        normalized: str,
        name: str,
        extension: str,
        is_dir: bool,
    ) -> RuleMatch | None:
        for source, section in _iter_rule_sections(self.excludes, "excludes"):
            for match in self._matches_section(
                section,
                normalized,
                name,
                extension,
                is_dir,
                policy=POLICY_DENY,
                source=source,
            ):
                return match
        return None

    def _matches_section(
        self,
        section: dict[str, Any],
        normalized: str,
        name: str,
        extension: str,
        is_dir: bool,
        *,
        policy: str,
        source: str,
    ) -> Iterable[RuleMatch]:
        for rule in _list_values(section, "paths", "path"):
            if _path_matches(normalized, str(rule)):
                yield RuleMatch(policy, source, f"path matched {rule}")

        for rule in _list_values(section, "path_globs", "globs", "glob"):
            if fnmatch.fnmatchcase(normalized.lower(), normalize_glob(str(rule)).lower()):
                yield RuleMatch(policy, source, f"path glob matched {rule}")

        for rule in _list_values(section, "extensions", "extension", "dangerous_extensions"):
            if extension and extension == _normalize_extension(str(rule)):
                yield RuleMatch(policy, source, f"extension matched {rule}")

        for rule in _list_values(section, "file_globs", "files", "file_patterns"):
            if fnmatch.fnmatchcase(name, str(rule).lower()):
                yield RuleMatch(policy, source, f"file glob matched {rule}")

        for rule in _list_values(section, "filenames", "file_names", "names"):
            if name == str(rule).lower():
                yield RuleMatch(policy, source, f"filename matched {rule}")

        for rule in _list_values(section, "dir_names", "directories", "directory_names"):
            if (is_dir and name == str(rule).lower()) or _path_has_segment(normalized, str(rule)):
                yield RuleMatch(policy, source, f"directory name matched {rule}")


def normalize_path(path: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(path))
    absolute = os.path.abspath(expanded)
    return absolute.replace("\\", "/")


def normalize_glob(pattern: str) -> str:
    return os.path.expandvars(os.path.expanduser(pattern)).replace("\\", "/")


def _path_matches(normalized_path: str, rule: str) -> bool:
    normalized_rule = normalize_path(rule).rstrip("/")
    path = normalized_path.rstrip("/")
    if os.name == "nt":
        path = path.lower()
        normalized_rule = normalized_rule.lower()
    return path == normalized_rule or path.startswith(normalized_rule + "/")


def _normalize_extension(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return value
    return value if value.startswith(".") else f".{value}"


def _path_has_segment(normalized_path: str, segment: str) -> bool:
    wanted = segment.strip().lower().strip("/")
    if not wanted:
        return False
    parts = [part.lower() for part in normalized_path.replace("\\", "/").split("/") if part]
    return wanted in parts


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_values(section: dict[str, Any], *keys: str) -> list[Any]:
    values: list[Any] = []
    for key in keys:
        raw = section.get(key)
        if raw is None:
            continue
        if isinstance(raw, (str, int, float)):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(raw)
    return values


def _iter_rule_sections(config: dict[str, Any], source: str) -> Iterable[tuple[str, dict[str, Any]]]:
    if not isinstance(config, dict):
        return
    yield source, config
    for key, value in config.items():
        if key == "version":
            continue
        if isinstance(value, dict):
            yield from _iter_rule_sections(value, f"{source}.{key}")
