from __future__ import annotations

import json

from pfkb.llm_client import (
    LLMAnalysisRequest,
    build_analysis_messages,
    coerce_analysis_response,
    parse_llm_json,
)


def test_parse_llm_json_accepts_fenced_json():
    payload = parse_llm_json(
        '```json\n{"title": "Demo", "summary": "ok", "model_tags": ["topic/privacy_policy"]}\n```'
    )

    assert payload["title"] == "Demo"
    assert payload["model_tags"] == ["topic/privacy_policy"]


def test_coerce_analysis_response_filters_unknown_tags_and_defaults_review_reason():
    request_data = LLMAnalysisRequest(
        path="notes.md",
        text="# Notes",
        content_type="document",
        rule_title="Notes",
        rule_summary="rule summary",
        rule_tags=["document"],
        allowed_tags=["topic/privacy_policy", "document/note"],
    )

    response = coerce_analysis_response(
        {
            "title": "Privacy Notes",
            "summary": "A privacy note.",
            "model_tags": ["topic/privacy_policy", "made_up"],
            "confidence": 0.82,
            "needs_human_review": False,
            "key_points": ["point"],
        },
        request_data,
    )

    assert response.tags == ["topic/privacy_policy"]
    assert response.review_reason == "llm_semantic_reviewed"
    assert response.key_points == ["point"]


def test_build_analysis_messages_bounds_text_and_requests_json():
    request_data = LLMAnalysisRequest(
        path="large.md",
        text="abcdef",
        content_type="document",
        rule_title="Large",
        rule_summary="rule",
        rule_tags=["document"],
        allowed_tags=["document/note"],
    )

    messages = build_analysis_messages(request_data, max_prompt_chars=3)
    user_payload = json.loads(messages[1]["content"])

    assert "JSON object" in messages[0]["content"]
    assert user_payload["file_text"] == "abc"
    assert user_payload["allowed_tags"] == ["document/note"]
