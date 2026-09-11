"""Render bounded Teams content from verified system-knowledge records."""

from __future__ import annotations

import json

from fdai_service_contracts.system_knowledge import SystemKnowledgeQueryResponse

_MAX_TEXT_CHARS = 4000
_MAX_PAYLOAD_BYTES = 24_000


def render_answer(response: SystemKnowledgeQueryResponse, *, locale: str) -> str:
    """Render design, implementation, limitations, and citations without source bodies."""

    korean = locale == "ko"
    if response.outcome != "answered":
        return (
            "검증된 FDAI 시스템 지식 레코드를 찾지 못했습니다. 기능 이름이나 설계 영역을 "
            "더 구체적으로 멘션해 주세요."
            if korean
            else (
                "No verified FDAI system-knowledge record matched. "
                "Mention a more specific capability or design area."
            )
        )
    lines: list[str] = []
    for match in response.matches[:3]:
        record = match.record
        lines.extend(
            [
                f"## {record.title}",
                "",
                (
                    f"**상태:** `{record.status.value}`  \n**소유자:** {record.owner}"
                    if korean
                    else f"**Status:** `{record.status.value}`  \n**Owner:** {record.owner}"
                ),
                "",
                "### 설계된 동작" if korean else "### Designed behavior",
                *[f"- {item}" for item in record.designed_behavior],
            ]
        )
        if record.implemented_behavior:
            lines.extend(
                [
                    "",
                    "### 구현 근거" if korean else "### Implemented evidence",
                    *[f"- {item}" for item in record.implemented_behavior],
                ]
            )
        if record.limitations:
            lines.extend(
                [
                    "",
                    "### 제한" if korean else "### Limitations",
                    *[f"- {item}" for item in record.limitations],
                ]
            )
        lines.extend(
            [
                "",
                "### 출처" if korean else "### Sources",
                *[
                    f"- `{source.path}:{source.line_start}` - `{source.symbol}`"
                    for source in record.sources[:4]
                ],
                "",
            ]
        )
    lines.append(
        "`execution_authority=false`이며 이 답변은 변경을 승인하지 않습니다."
        if korean
        else "`execution_authority=false`; this answer authorizes no change."
    )
    rendered = "\n".join(lines)
    return rendered[:_MAX_TEXT_CHARS]


def teams_payload(
    response: SystemKnowledgeQueryResponse,
    *,
    locale: str,
    reply_to_id: str,
) -> dict[str, object]:
    """Build one bounded Adaptive Card with a plain-text fallback."""

    text = render_answer(response, locale=locale)
    payload: dict[str, object] = {
        "type": "message",
        "replyToId": reply_to_id,
        "text": text,
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.5",
                    "body": [{"type": "TextBlock", "text": text, "wrap": True}],
                },
            }
        ],
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        return {"type": "message", "replyToId": reply_to_id, "text": text[:2000]}
    return payload


def outgoing_webhook_payload(
    response: SystemKnowledgeQueryResponse,
    *,
    locale: str,
) -> dict[str, object]:
    """Build one bounded synchronous Outgoing Webhook response."""

    text = render_answer(response, locale=locale)
    payload: dict[str, object] = {
        "type": "message",
        "text": text,
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [{"type": "TextBlock", "text": text, "wrap": True}],
                },
            }
        ],
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        return {"type": "message", "text": text[:2000]}
    return payload


__all__ = ["outgoing_webhook_payload", "render_answer", "teams_payload"]
