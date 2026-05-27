from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml


@dataclass(frozen=True)
class TagDefinition:
    id: str
    zh: str
    en: str
    dimension: str
    description: str
    aliases: tuple[str, ...] = ()
    parent: str = ""
    recommended_policy: str = ""
    default_sensitivity: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "zh": self.zh,
            "en": self.en,
            "dimension": self.dimension,
            "description": self.description,
            "aliases": list(self.aliases),
            "parent": self.parent,
            "recommended_policy": self.recommended_policy,
            "default_sensitivity": self.default_sensitivity,
        }


def load_tags_config(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if path is None:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Tags config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8-sig") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Tags config must be a mapping: {config_path}")
    return loaded


def describe_tags_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    assistant = _mapping(config.get("assistant"))
    definitions = tag_definitions(config)
    dimensions = _dimension_items(config)
    tags_by_dimension: dict[str, int] = {}
    for definition in definitions:
        tags_by_dimension[definition.dimension] = tags_by_dimension.get(definition.dimension, 0) + 1
    return {
        "version": config.get("version", 1),
        "purpose": str(
            assistant.get(
                "purpose",
                "定义个人文件知识库的分层标签、结构化属性和人工确认字段。",
            )
        ),
        "setup_questions": _string_list(assistant.get("setup_questions")),
        "design_principles": _string_list(assistant.get("design_principles")),
        "inherited_patterns": _mapping_list(assistant.get("inherited_patterns")),
        "naming": _mapping(config.get("naming")),
        "output_fields": _mapping(config.get("output_fields")),
        "dimensions": dimensions,
        "tag_count": len(definitions),
        "tags_by_dimension": tags_by_dimension,
        "tags": [definition.as_dict() for definition in definitions],
    }


def tag_definitions(config: dict[str, Any] | None) -> list[TagDefinition]:
    config = config or {}
    definitions: list[TagDefinition] = []
    for item in _mapping_list(config.get("tags")):
        tag_id = str(item.get("id") or "").strip()
        if not tag_id:
            continue
        definitions.append(
            TagDefinition(
                id=tag_id,
                zh=str(item.get("zh") or tag_id),
                en=str(item.get("en") or tag_id),
                dimension=str(item.get("dimension") or tag_id.split("/", 1)[0]),
                description=str(item.get("description") or ""),
                aliases=tuple(_string_list(item.get("aliases"))),
                parent=str(item.get("parent") or ""),
                recommended_policy=str(item.get("recommended_policy") or ""),
                default_sensitivity=str(item.get("default_sensitivity") or ""),
            )
        )
    return definitions


class TagRegistry:
    def __init__(self, config: dict[str, Any] | None = None):
        self.definitions = tag_definitions(config)
        self.by_id = {definition.id: definition for definition in self.definitions}
        self.aliases: dict[str, str] = {}
        for definition in self.definitions:
            self.aliases[definition.id.lower()] = definition.id
            self.aliases[definition.zh.lower()] = definition.id
            self.aliases[definition.en.lower()] = definition.id
            for alias in definition.aliases:
                self.aliases[alias.lower()] = definition.id

    def normalize(self, tag: str) -> str:
        return self.aliases.get(str(tag).strip().lower(), str(tag).strip())

    def label(self, tag: str) -> str:
        definition = self.by_id.get(self.normalize(tag))
        return definition.zh if definition else str(tag)

    def format(self, tag: str) -> str:
        normalized = self.normalize(tag)
        label = self.label(normalized)
        if label == normalized:
            return f"`{normalized}`"
        return f"{label}（`{normalized}`）"


def filter_tags(
    definitions: list[TagDefinition],
    *,
    dimension: str | None = None,
    query: str | None = None,
) -> list[TagDefinition]:
    query_text = (query or "").strip().lower()
    result: list[TagDefinition] = []
    for definition in definitions:
        if dimension and definition.dimension != dimension:
            continue
        if query_text and query_text not in _search_text(definition):
            continue
        result.append(definition)
    return result


def _search_text(definition: TagDefinition) -> str:
    return " ".join(
        [
            definition.id,
            definition.zh,
            definition.en,
            definition.dimension,
            definition.description,
            " ".join(definition.aliases),
        ]
    ).lower()


def _dimension_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _mapping_list(config.get("dimensions")):
        dimension_id = str(item.get("id") or "").strip()
        if not dimension_id:
            continue
        items.append(
            {
                "id": dimension_id,
                "zh": str(item.get("zh") or dimension_id),
                "purpose": str(item.get("purpose") or ""),
                "user_editable": bool(item.get("user_editable", True)),
            }
        )
    return items


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
