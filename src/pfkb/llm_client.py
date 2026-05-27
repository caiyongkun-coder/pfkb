from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import error, request
import json
import os
import re


DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_PROMPT_CHARS = 24_000


class LLMClientError(RuntimeError):
    """Raised when an LLM provider cannot produce a usable analysis."""


@dataclass(frozen=True)
class LLMAnalysisRequest:
    path: str
    text: str
    content_type: str
    rule_title: str
    rule_summary: str
    rule_tags: list[str]
    allowed_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LLMAnalysisResponse:
    title: str
    summary: str
    tags: list[str]
    confidence: float
    needs_human_review: bool
    review_reason: str
    key_points: list[str]
    model_notes: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMAnalyzer(Protocol):
    def analyze(self, request_data: LLMAnalysisRequest) -> LLMAnalysisResponse:
        ...


class ConfiguredLLMClient:
    def __init__(self, config: dict[str, Any] | None, *, method: str):
        self.config = config or {}
        self.method = method
        if method not in {"local-llm", "cloud-llm"}:
            raise ValueError(f"unsupported LLM method: {method}")

    def analyze(self, request_data: LLMAnalysisRequest) -> LLMAnalysisResponse:
        runtime = self._runtime()
        messages = build_analysis_messages(
            request_data,
            max_prompt_chars=_int_setting(runtime, "max_prompt_chars", DEFAULT_MAX_PROMPT_CHARS),
        )
        content = self._call_provider(runtime, messages)
        parsed = parse_llm_json(content)
        return coerce_analysis_response(parsed, request_data)

    def _runtime(self) -> dict[str, Any]:
        section_name = "local" if self.method == "local-llm" else "cloud"
        section = _mapping(self.config.get(section_name))
        llm = _mapping(self.config.get("llm"))
        analysis = _mapping(self.config.get("analysis"))
        provider = str(section.get("provider") or llm.get("provider") or "").strip()
        model = str(section.get("model") or llm.get("model") or "").strip()
        endpoint = str(section.get("endpoint") or llm.get("endpoint") or "").strip()
        if not provider:
            raise LLMClientError(f"{section_name} LLM provider is not configured")
        if not model:
            raise LLMClientError(f"{section_name} LLM model is not configured")
        return {
            **section,
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "timeout_seconds": _int_setting(analysis, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            "temperature": _float_setting(analysis, "temperature", DEFAULT_TEMPERATURE),
            "max_prompt_chars": _int_setting(analysis, "max_prompt_chars", DEFAULT_MAX_PROMPT_CHARS),
        }

    def _call_provider(self, runtime: dict[str, Any], messages: list[dict[str, str]]) -> str:
        provider = str(runtime.get("provider") or "").lower()
        if provider == "ollama":
            return _call_ollama(runtime, messages)
        if provider in {"openai", "compatible", "lmstudio", "llama.cpp", "vllm"}:
            return _call_openai_compatible(runtime, messages, provider=provider)
        raise LLMClientError(f"unsupported LLM provider: {provider}")


def build_analysis_messages(
    request_data: LLMAnalysisRequest,
    *,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> list[dict[str, str]]:
    allowed_tags = request_data.allowed_tags[:160]
    text = request_data.text[:max_prompt_chars] if max_prompt_chars > 0 else request_data.text
    schema_hint = {
        "title": "简短标题",
        "summary": "1-3 句中文摘要，说明文件真正讲什么和可用于什么",
        "model_tags": ["必须优先从 allowed_tags 中选择"],
        "confidence": 0.0,
        "needs_human_review": True,
        "review_reason": "llm_low_confidence 或 llm_semantic_reviewed",
        "key_points": ["最多 5 条关键点"],
    }
    system = (
        "你是 PFKB 个人文件知识库的本地内容理解引擎。"
        "你只根据用户提供的文件正文分析，不要假装读取了其他文件。"
        "必须只输出一个 JSON object，不要 Markdown，不要代码围栏。"
        "标签必须优先从 allowed_tags 中选择；如果不确定，把 needs_human_review 设为 true。"
    )
    user = {
        "task": "总结文件内容、选择结构化标签、判断是否需要人工复核。",
        "output_schema": schema_hint,
        "path": request_data.path,
        "content_type": request_data.content_type,
        "rule_title": request_data.rule_title,
        "rule_summary": request_data.rule_summary,
        "rule_tags": request_data.rule_tags,
        "allowed_tags": allowed_tags,
        "file_text": text,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, sort_keys=True)},
    ]


def parse_llm_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise LLMClientError("LLM response did not contain a JSON object") from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"LLM response JSON could not be parsed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMClientError("LLM response JSON must be an object")
    return parsed


def coerce_analysis_response(
    payload: dict[str, Any],
    request_data: LLMAnalysisRequest,
) -> LLMAnalysisResponse:
    title = _clean_text(payload.get("title")) or request_data.rule_title
    summary = _clean_text(payload.get("summary")) or request_data.rule_summary
    raw_tags = payload.get("model_tags", payload.get("tags", []))
    tags = _normalize_tags(raw_tags, allowed_tags=request_data.allowed_tags)
    if not tags:
        tags = request_data.rule_tags[:]
    confidence = _clamp_float(payload.get("confidence"), default=0.5)
    needs_human_review = bool(payload.get("needs_human_review", confidence < 0.7))
    review_reason = _clean_text(payload.get("review_reason"))
    if review_reason not in {"llm_low_confidence", "llm_semantic_reviewed"}:
        review_reason = "llm_low_confidence" if needs_human_review or confidence < 0.7 else "llm_semantic_reviewed"
    key_points = _string_list(payload.get("key_points"))[:5]
    model_notes = _clean_text(payload.get("model_notes")) or "LLM API 根据提取文本生成；未直接读取原始文件。"
    return LLMAnalysisResponse(
        title=title,
        summary=summary,
        tags=tags,
        confidence=confidence,
        needs_human_review=needs_human_review,
        review_reason=review_reason,
        key_points=key_points,
        model_notes=model_notes,
        raw=payload,
    )


def _call_openai_compatible(runtime: dict[str, Any], messages: list[dict[str, str]], *, provider: str) -> str:
    endpoint = str(runtime.get("endpoint") or "").strip()
    if provider == "openai" and not endpoint:
        endpoint = "https://api.openai.com/v1/chat/completions"
    endpoint = _chat_completions_url(endpoint)
    api_key = _api_key(runtime, default_env="OPENAI_API_KEY" if provider == "openai" else "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "openai":
        raise LLMClientError("missing cloud API key: set OPENAI_API_KEY or cloud.api_key_env")
    payload = {
        "model": runtime["model"],
        "messages": messages,
        "temperature": _float_setting(runtime, "temperature", DEFAULT_TEMPERATURE),
        "response_format": {"type": "json_object"},
    }
    data = _post_json(endpoint, payload, headers=headers, timeout=_int_setting(runtime, "timeout_seconds", 60))
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMClientError("OpenAI-compatible response did not include choices[0].message.content") from exc


def _call_ollama(runtime: dict[str, Any], messages: list[dict[str, str]]) -> str:
    endpoint = str(runtime.get("endpoint") or "http://localhost:11434").rstrip("/")
    url = endpoint + "/api/chat"
    payload = {
        "model": runtime["model"],
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": _float_setting(runtime, "temperature", DEFAULT_TEMPERATURE)},
    }
    data = _post_json(url, payload, timeout=_int_setting(runtime, "timeout_seconds", 60))
    try:
        return str(data["message"]["content"])
    except (KeyError, TypeError) as exc:
        raise LLMClientError("Ollama response did not include message.content") from exc


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers or {"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - user-configured LLM endpoint.
            response_body = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise LLMClientError(f"LLM API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise LLMClientError(f"LLM API request failed: {exc}") from exc
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LLMClientError(f"LLM API response was not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMClientError("LLM API response must be a JSON object")
    return parsed


def _chat_completions_url(endpoint: str) -> str:
    if not endpoint:
        raise LLMClientError("OpenAI-compatible endpoint is not configured")
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"


def _api_key(runtime: dict[str, Any], *, default_env: str) -> str:
    env_name = str(runtime.get("api_key_env") or default_env or "").strip()
    if not env_name:
        return ""
    return os.environ.get(env_name, "")


def _normalize_tags(value: Any, *, allowed_tags: list[str]) -> list[str]:
    allowed = {tag.lower(): tag for tag in allowed_tags}
    result: list[str] = []
    for item in _string_list(value):
        normalized = item.strip().lower()
        if not normalized:
            continue
        if allowed and normalized not in allowed:
            continue
        tag = allowed.get(normalized, normalized)
        if tag not in result:
            result.append(tag)
    return result[:8]


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


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _int_setting(mapping: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(mapping.get(key, default))
    except (TypeError, ValueError):
        return default


def _float_setting(mapping: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(mapping.get(key, default))
    except (TypeError, ValueError):
        return default
