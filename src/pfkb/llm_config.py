from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import os

import yaml


def load_llm_config(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if path is None:
        return default_llm_config()
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"LLM config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8-sig") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"LLM config must be a mapping: {config_path}")
    return loaded


def default_llm_config() -> dict[str, Any]:
    return {
        "version": 1,
        "llm": {"mode": "rules", "provider": "none", "model": "", "endpoint": ""},
        "analysis": {"max_prompt_chars": 24000, "timeout_seconds": 60, "temperature": 0.1},
        "local": {
            "enabled": False,
            "provider": "ollama",
            "model": "",
            "endpoint": "http://localhost:11434",
            "allow_network_loopback_only": True,
        },
        "cloud": {
            "enabled": False,
            "provider": "openai",
            "model": "",
            "endpoint": "",
            "api_key_env": "OPENAI_API_KEY",
            "risk_acknowledged": False,
            "allowed_policies": ["allow"],
            "forbidden_policies": ["deny", "metadata_only", "no_embedding"],
            "allowed_paths": [],
        },
    }


def describe_llm_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or default_llm_config()
    assistant = _mapping(config.get("assistant"))
    llm = _mapping(config.get("llm"))
    analysis = _mapping(config.get("analysis"))
    local = _mapping(config.get("local"))
    cloud = _mapping(config.get("cloud"))
    return {
        "version": config.get("version", 1),
        "purpose": str(
            assistant.get(
                "purpose",
                "配置内容理解阶段是否使用规则、本地模型或云端模型。",
            )
        ),
        "mode": str(llm.get("mode", "rules")),
        "provider": str(llm.get("provider", "none")),
        "model": str(llm.get("model", "")),
        "endpoint": str(llm.get("endpoint", "")),
        "analysis_max_prompt_chars": _int_value(analysis.get("max_prompt_chars"), 24000),
        "analysis_timeout_seconds": _int_value(analysis.get("timeout_seconds"), 60),
        "analysis_temperature": _float_value(analysis.get("temperature"), 0.1),
        "local_enabled": bool(local.get("enabled", False)),
        "local_provider": str(local.get("provider", "")),
        "local_model": str(local.get("model", "")),
        "local_endpoint": str(local.get("endpoint", "")),
        "local_loopback_only": bool(local.get("allow_network_loopback_only", True)),
        "local_ready": local_allowed_for_config(config),
        "cloud_enabled": bool(cloud.get("enabled", False)),
        "cloud_provider": str(cloud.get("provider", "")),
        "cloud_model": str(cloud.get("model", "")),
        "cloud_endpoint": str(cloud.get("endpoint", "")),
        "cloud_api_key_env": str(cloud.get("api_key_env", "OPENAI_API_KEY")),
        "cloud_risk_acknowledged": bool(cloud.get("risk_acknowledged", False)),
        "cloud_allowed_paths": _string_list(cloud.get("allowed_paths")),
        "cloud_allowed_policies": _string_list(cloud.get("allowed_policies")) or ["allow"],
        "cloud_forbidden_policies": _string_list(cloud.get("forbidden_policies"))
        or ["deny", "metadata_only", "no_embedding"],
        "setup_questions": _string_list(assistant.get("setup_questions")),
        "privacy_notes": _string_list(assistant.get("privacy_notes")),
    }


def local_allowed_for_config(config: dict[str, Any] | None) -> bool:
    config = config or default_llm_config()
    llm = _mapping(config.get("llm"))
    local = _mapping(config.get("local"))
    if str(llm.get("mode", "rules")) != "local":
        return False
    if not bool(local.get("enabled", False)):
        return False
    if not str(local.get("provider") or llm.get("provider") or "").strip():
        return False
    if not str(local.get("model") or llm.get("model") or "").strip():
        return False
    endpoint = str(local.get("endpoint") or llm.get("endpoint") or "").strip()
    if bool(local.get("allow_network_loopback_only", True)) and not endpoint_is_loopback(endpoint):
        return False
    return True


def cloud_allowed_for_path(path: str, access_policy: str, config: dict[str, Any] | None) -> bool:
    config = config or default_llm_config()
    llm = _mapping(config.get("llm"))
    cloud = _mapping(config.get("cloud"))
    if str(llm.get("mode", "rules")) != "cloud":
        return False
    if not bool(cloud.get("enabled", False)):
        return False
    if not bool(cloud.get("risk_acknowledged", False)):
        return False
    allowed_policies = set(_string_list(cloud.get("allowed_policies")) or ["allow"])
    forbidden_policies = set(
        _string_list(cloud.get("forbidden_policies")) or ["deny", "metadata_only", "no_embedding"]
    )
    if access_policy in forbidden_policies or access_policy not in allowed_policies:
        return False
    allowed_paths = _string_list(cloud.get("allowed_paths"))
    if not allowed_paths:
        return False
    return any(_path_is_under(path, allowed_path) for allowed_path in allowed_paths)


def endpoint_is_loopback(endpoint: str) -> bool:
    if not endpoint:
        return False
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def _path_is_under(path: str, root: str) -> bool:
    normalized_path = _normalize(path)
    normalized_root = _normalize(root).rstrip("/")
    if os.name == "nt":
        normalized_path = normalized_path.lower()
        normalized_root = normalized_root.lower()
    return normalized_path == normalized_root or normalized_path.startswith(normalized_root + "/")


def _normalize(path: str) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path))).replace("\\", "/")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
