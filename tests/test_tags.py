from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from pfkb.cli import main as cli_main
from pfkb.tags import TagRegistry, describe_tags_config, load_tags_config


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = cli_main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        else:
            code = int(result)
    return code, stdout.getvalue(), stderr.getvalue()


def _tags_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "tags.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "assistant:",
                '  purpose: "tag taxonomy fixture"',
                "  design_principles:",
                '    - "Keep automatic and accepted tags separate."',
                "dimensions:",
                "  - id: topic",
                '    zh: "知识主题"',
                '    purpose: "What the file is about."',
                "tags:",
                "  - id: topic/privacy_policy",
                '    zh: "隐私策略"',
                '    en: "Privacy policy"',
                "    dimension: topic",
                '    description: "Controls read and embedding boundaries."',
                "    aliases:",
                "      - privacy",
                "      - metadata_only",
                "  - id: workflow/waiting_review",
                '    zh: "待复核"',
                '    en: "Waiting review"',
                "    dimension: workflow",
                '    description: "Needs human confirmation."',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_tags_config_is_agent_readable_and_normalizes_aliases(tmp_path):
    config = load_tags_config(_tags_fixture(tmp_path))
    summary = describe_tags_config(config)

    assert summary["purpose"] == "tag taxonomy fixture"
    assert summary["tag_count"] == 2
    assert summary["tags_by_dimension"]["topic"] == 1
    registry = TagRegistry(config)
    assert registry.normalize("privacy") == "topic/privacy_policy"
    assert registry.label("metadata_only") == "隐私策略"
    assert registry.format("topic/privacy_policy") == "隐私策略（`topic/privacy_policy`）"


def test_tags_cli_explains_and_filters_taxonomy(tmp_path):
    tags_config = _tags_fixture(tmp_path)

    text_code, text_out, text_err = _run_cli(
        ["tags", "--tags-config", str(tags_config), "--dimension", "topic"]
    )
    assert text_code == 0, text_err
    assert "tags_config:" in text_out
    assert "tag taxonomy fixture" in text_out
    assert "topic/privacy_policy" in text_out
    assert "workflow/waiting_review" not in text_out

    json_code, json_out, json_err = _run_cli(
        ["tags", "--tags-config", str(tags_config), "--search", "metadata_only", "--json"]
    )
    assert json_code == 0, json_err
    payload = json.loads(json_out)
    assert payload["filtered_tag_count"] == 1
    assert payload["tags"][0]["id"] == "topic/privacy_policy"
