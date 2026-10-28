"""Map one redacted model-call trace to OpenInference span attributes and timing.

The trace comes from ``fdai.delivery.azure.llm.model_trace.complete_model_trace`` and is already
redacted and bounded by the provider-input minimization pipeline. Content attributes are added
only when the caller opts in; otherwise the span carries timing, token counts, and hashes only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

_NS = 1_000_000_000
_USAGE_ATTRIBUTES = (
    ("prompt_tokens", "llm.token_count.prompt"),
    ("completion_tokens", "llm.token_count.completion"),
    ("total_tokens", "llm.token_count.total"),
    ("cached_tokens", "llm.token_count.prompt_details.cache_read"),
)


def model_trace_timing(trace: Mapping[str, object]) -> tuple[int, int] | None:
    """Return ``(start_ns, end_ns)`` from the trace timestamps, or ``None`` when unusable."""
    try:
        start = datetime.fromisoformat(str(trace["started_at"]))
        end = datetime.fromisoformat(str(trace["completed_at"]))
    except (KeyError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None:
        return None
    start_ns, end_ns = int(start.timestamp() * _NS), int(end.timestamp() * _NS)
    return (start_ns, end_ns) if end_ns >= start_ns else None


def model_trace_attributes(
    trace: Mapping[str, object],
    *,
    correlation_id: str | None,
    capture_content: bool,
) -> dict[str, str | int]:
    """Build bounded span attributes; message text only when ``capture_content`` is true."""
    kind = str(trace.get("kind", "unknown"))
    attributes: dict[str, str | int] = {
        "openinference.span.kind": "LLM",
        "llm.model_name": str(trace.get("model", "unknown")),
        "fdai.call_kind": kind,
        "fdai.call_id": str(trace.get("call_id", "")),
        "fdai.usage_scope": "operator_chat",
        "fdai.status": str(trace.get("status", "unknown")),
    }
    if correlation_id:
        attributes["session.id"] = correlation_id
    duration = trace.get("duration_ms")
    if isinstance(duration, int) and not isinstance(duration, bool):
        attributes["fdai.duration_ms"] = duration
    usage = trace.get("usage")
    if isinstance(usage, Mapping):
        for source, target in _USAGE_ATTRIBUTES:
            value = usage.get(source)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                attributes[target] = value
    request = trace.get("request")
    response = trace.get("response")
    if isinstance(request, Mapping) and isinstance(request.get("sha256"), str):
        attributes["fdai.request_sha256"] = str(request["sha256"])
    if isinstance(response, Mapping) and isinstance(response.get("sha256"), str):
        attributes["fdai.response_sha256"] = str(response["sha256"])
    redactions = trace.get("redactions")
    if isinstance(redactions, list):
        attributes["fdai.redaction_replacements"] = sum(
            item["replacements"]
            for item in redactions
            if isinstance(item, Mapping) and isinstance(item.get("replacements"), int)
        )
    if capture_content:
        attributes.update(_content_attributes(request, response))
    return attributes


def _content_attributes(request: object, response: object) -> dict[str, str | int]:
    attributes: dict[str, str | int] = {}
    messages = request.get("messages") if isinstance(request, Mapping) else None
    last_user = ""
    for index, message in enumerate(messages if isinstance(messages, list) else ()):
        if not isinstance(message, Mapping):
            continue
        role, content = str(message.get("role", "")), str(message.get("content", ""))
        attributes[f"llm.input_messages.{index}.message.role"] = role
        attributes[f"llm.input_messages.{index}.message.content"] = content
        if role == "user":
            last_user = content
    if last_user:
        attributes["input.value"] = last_user
        attributes["input.mime_type"] = "text/plain"
    answer = response.get("content") if isinstance(response, Mapping) else None
    if isinstance(answer, str) and answer:
        attributes["output.value"] = answer
        attributes["output.mime_type"] = _mime_type(answer)
        attributes["llm.output_messages.0.message.role"] = "assistant"
        attributes["llm.output_messages.0.message.content"] = answer
    return attributes


def _mime_type(value: str) -> str:
    try:
        json.loads(value)
    except ValueError:
        return "text/plain"
    return "application/json"
