"""Canonical rendering and replay projection for measured LLM usage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_llm_usage import (
    parse_llm_usage_analysis_context,
)


def response_llm_usage_analysis_context(
    view_context: Mapping[str, Any],
    *,
    verification_status: str,
) -> dict[str, object] | None:
    """Project a verified usage anchor from server-owned tool evidence."""

    if verification_status not in {"verified", "corrected"}:
        return None
    evidence = view_context.get("_tool_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("tool") != "query_llm_usage":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") not in {"matched", "none"}:
        return None
    return parse_llm_usage_analysis_context(evidence.get("analysis_context"))


def llm_usage_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    raw = result.get("evidence_refs")
    if not isinstance(raw, list):
        return ()
    return tuple(
        dict.fromkeys(item for item in raw[:8] if isinstance(item, str) and 0 < len(item) <= 1_024)
    )


def render_llm_usage_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
    answer_format: str,
) -> str | None:
    """Render measured usage without estimating price or invoice cost."""

    if evidence.get("tool") != "query_llm_usage":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    rows = result.get("rows")
    total = result.get("total")
    if not isinstance(rows, list) or not isinstance(total, Mapping):
        return None
    if not all(_valid_usage_row(row) for row in rows):
        return None
    total_tokens = total.get("total_tokens")
    prompt_tokens = total.get("prompt_tokens")
    completion_tokens = total.get("completion_tokens")
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (total_tokens, prompt_tokens, completion_tokens)
    ):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    window_start = result.get("window_start")
    window_end = result.get("window_end")
    if not isinstance(window_start, str) or not isinstance(window_end, str):
        return None
    if result.get("status") == "none":
        return (
            f"{window_start}부터 {window_end}까지 측정된 LLM 호출이 없습니다."
            if korean
            else f"No measured LLM calls were recorded from {window_start} to {window_end}."
        )
    if answer_format == "chart" and rows:
        chart = {
            "type": "line" if result.get("group_by") == "day" else "bar",
            "title": "일별 LLM 토큰 사용량" if korean else "LLM token usage",
            "unit": "tokens",
            "data": [{"label": str(row["key"]), "value": int(row["total_tokens"])} for row in rows],
        }
        return f"```chart\n{json.dumps(chart, ensure_ascii=False, separators=(',', ':'))}\n```"
    if answer_format == "table" and rows:
        headers = (
            "| 구분 | 호출 | 입력 토큰 | 출력 토큰 | 전체 토큰 |"
            if korean
            else "| Group | Calls | Input tokens | Output tokens | Total tokens |"
        )
        lines = [headers, "|---|---:|---:|---:|---:|"]
        lines.extend(
            f"| {row['key']} | {row['invocations']} | {row['prompt_tokens']} | "
            f"{row['completion_tokens']} | {row['total_tokens']} |"
            for row in rows
        )
        return "\n".join(lines)
    return (
        f"측정된 LLM 호출은 {total.get('invocations')}회이며, 전체 토큰은 "
        f"{total_tokens}개입니다. 입력 토큰 {prompt_tokens}개, 출력 토큰 "
        f"{completion_tokens}개입니다. 금액은 측정된 가격 근거가 없어 추정하지 않았습니다."
        if korean
        else (
            f"Measured LLM usage contains {total.get('invocations')} calls and "
            f"{total_tokens} total tokens: {prompt_tokens} input and "
            f"{completion_tokens} output tokens. No monetary amount was estimated "
            "without measured pricing evidence."
        )
    )


def _valid_usage_row(value: object) -> bool:
    if not isinstance(value, Mapping) or not isinstance(value.get("key"), str):
        return False
    return all(
        isinstance(value.get(field), int)
        and not isinstance(value.get(field), bool)
        and value.get(field, -1) >= 0
        for field in (
            "invocations",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        )
    )


__all__ = [
    "llm_usage_evidence_refs",
    "render_llm_usage_answer",
    "response_llm_usage_analysis_context",
]
