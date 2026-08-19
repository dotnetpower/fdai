"""Pure bounded Slack Block Kit and Teams Adaptive Card renderers."""

from __future__ import annotations

from typing import cast

from fdai_operator_service.families.conversation.channel_edge.presentation import (
    PresentationCapabilities,
    PresentationEnvelope,
    PresentationPayload,
    PresentationRenderError,
    build_fallback_text,
    serialized_size,
)
from fdai_operator_service.families.conversation.contracts import JsonObject, JsonValue

SLACK_CAPABILITIES = PresentationCapabilities(
    profile_id="slack-block-kit-v1",
    max_text_chars=12_000,
    max_serialized_bytes=50_000,
    max_blocks=50,
    max_block_text_chars=2_900,
    max_fields=40,
    max_actions=1,
)
TEAMS_CAPABILITIES = PresentationCapabilities(
    profile_id="teams-adaptive-card-v1",
    max_text_chars=4_000,
    max_serialized_bytes=24_000,
    max_blocks=24,
    max_block_text_chars=4_000,
    max_fields=40,
    max_actions=1,
)


class SlackPresentationRenderer:
    """Build Block Kit JSON without credentials, endpoints, or I/O."""

    def render(self, envelope: PresentationEnvelope) -> PresentationPayload:
        fallback, degraded = build_fallback_text(envelope, SLACK_CAPABILITIES)
        blocks: list[JsonValue] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _mrkdwn(chunk)}}
            for chunk in _chunks(fallback, SLACK_CAPABILITIES.max_block_text_chars)
        ]
        fallback_blocks = len(blocks)
        fields_used = 0
        omitted = 0
        for section in envelope.sections:
            if len(blocks) >= SLACK_CAPABILITIES.max_blocks:
                omitted += 1
                continue
            remaining = max(0, SLACK_CAPABILITIES.max_fields - fields_used)
            facts = section.facts[:remaining]
            heading = f"*{_mrkdwn(section.title)}*"
            if section.description is not None:
                heading += f"\n{_mrkdwn(section.description)}"
            block: JsonObject = {
                "type": "section",
                "text": {"type": "mrkdwn", "text": heading},
            }
            if facts:
                block["fields"] = [
                    {"type": "mrkdwn", "text": f"*{_mrkdwn(fact.label)}*\n{_mrkdwn(fact.value)}"}
                    for fact in facts[:10]
                ]
                fields_used += min(len(facts), 10)
            blocks.append(block)
            if len(facts) < len(section.facts) or len(facts) > 10:
                omitted += 1
        if envelope.web_url is not None:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in FDAI Console"},
                            "url": envelope.web_url,
                        }
                    ],
                }
            )
        payload: JsonObject = {"text": fallback, "blocks": blocks}
        if (
            serialized_size(cast(dict[str, object], payload))
            > SLACK_CAPABILITIES.max_serialized_bytes
        ):
            payload = {"text": fallback, "blocks": blocks[:fallback_blocks]}
            omitted = max(omitted, len(envelope.sections))
            degraded = True
        _ensure_size(payload, SLACK_CAPABILITIES)
        return PresentationPayload(payload, fallback, degraded or omitted > 0, omitted)


class TeamsPresentationRenderer:
    """Build Adaptive Card JSON without credentials, endpoints, or I/O."""

    def render(self, envelope: PresentationEnvelope) -> PresentationPayload:
        fallback, degraded = build_fallback_text(envelope, TEAMS_CAPABILITIES)
        body: list[JsonValue] = [{"type": "TextBlock", "text": fallback, "wrap": True}]
        fields_used = 0
        omitted = 0
        for section in envelope.sections:
            if len(body) >= TEAMS_CAPABILITIES.max_blocks:
                omitted += 1
                continue
            remaining = max(0, TEAMS_CAPABILITIES.max_fields - fields_used)
            facts = section.facts[:remaining]
            if not facts and section.description is None:
                omitted += 1
                continue
            items: list[JsonValue] = [
                {"type": "TextBlock", "text": section.title, "weight": "Bolder", "wrap": True}
            ]
            if section.description is not None:
                items.append(
                    {
                        "type": "TextBlock",
                        "text": section.description,
                        "wrap": True,
                        "isSubtle": True,
                    }
                )
            if facts:
                items.append(
                    {
                        "type": "FactSet",
                        "facts": [{"title": fact.label, "value": fact.value} for fact in facts],
                    }
                )
                fields_used += len(facts)
            body.append({"type": "Container", "items": items})
            if len(facts) < len(section.facts):
                omitted += 1
        actions: list[JsonValue] = (
            [{"type": "Action.OpenUrl", "title": "Open in FDAI Console", "url": envelope.web_url}]
            if envelope.web_url is not None
            else []
        )
        payload = _teams_payload(body, actions)
        if (
            serialized_size(cast(dict[str, object], payload))
            > TEAMS_CAPABILITIES.max_serialized_bytes
        ):
            payload = _teams_payload(body[:1], actions)
            omitted = max(omitted, len(envelope.sections))
            degraded = True
        _ensure_size(payload, TEAMS_CAPABILITIES)
        return PresentationPayload(payload, fallback, degraded or omitted > 0, omitted)


def _teams_payload(body: list[JsonValue], actions: list[JsonValue]) -> JsonObject:
    content: JsonObject = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
    }
    if actions:
        content["actions"] = actions
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": content,
            }
        ],
    }


def _ensure_size(payload: JsonObject, capabilities: PresentationCapabilities) -> None:
    if serialized_size(cast(dict[str, object], payload)) > capabilities.max_serialized_bytes:
        raise PresentationRenderError("mandatory channel payload exceeds the provider limit")


def _chunks(value: str, maximum: int) -> tuple[str, ...]:
    return tuple(value[index : index + maximum] for index in range(0, len(value), maximum))


def _mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = [
    "SLACK_CAPABILITIES",
    "TEAMS_CAPABILITIES",
    "SlackPresentationRenderer",
    "TeamsPresentationRenderer",
]
