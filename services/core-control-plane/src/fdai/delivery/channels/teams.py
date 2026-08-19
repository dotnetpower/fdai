"""Pure Teams Adaptive Card renderer for canonical conversation presentation."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.delivery.channels.common import build_fallback_text, ensure_payload_fits, payload_size
from fdai.shared.providers.channel_presentation import (
    ChannelPresentationCapabilities,
    ChannelPresentationEnvelope,
    ChannelPresentationPayload,
)

TEAMS_PRESENTATION_CAPABILITIES = ChannelPresentationCapabilities(
    profile_id="teams-adaptive-card-v1",
    max_text_chars=4_000,
    max_serialized_bytes=24_000,
    max_blocks=24,
    max_block_text_chars=4_000,
    max_fields=40,
    max_actions=1,
    supports_edits=True,
    supports_threads=True,
    supports_progress=True,
)


class TeamsPresentationRenderer:
    """Build Adaptive Card JSON without credentials, HTTP, or acknowledgement."""

    renderer_id = "teams-adaptive-card"

    def __init__(
        self,
        capabilities: ChannelPresentationCapabilities = TEAMS_PRESENTATION_CAPABILITIES,
    ) -> None:
        self.capabilities = capabilities

    def render(self, envelope: ChannelPresentationEnvelope) -> ChannelPresentationPayload:
        fallback, degraded = build_fallback_text(envelope, self.capabilities)
        body: list[dict[str, object]] = [{"type": "TextBlock", "text": fallback, "wrap": True}]
        fields_used = 0
        omitted = 0
        for section in envelope.sections:
            if len(body) >= self.capabilities.max_blocks:
                omitted += 1
                continue
            remaining = max(0, self.capabilities.max_fields - fields_used)
            facts = section.facts[:remaining]
            if not facts and section.description is None:
                omitted += 1
                continue
            items: list[dict[str, object]] = [
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
        actions: list[dict[str, object]] = (
            [{"type": "Action.OpenUrl", "title": "Open in FDAI Console", "url": envelope.web_url}]
            if envelope.web_url is not None and self.capabilities.max_actions > 0
            else []
        )
        payload = _teams_payload(body, actions)
        if payload_size(payload) > self.capabilities.max_serialized_bytes:
            omitted = max(omitted, len(envelope.sections))
            payload = _teams_payload(body[:1], actions)
            degraded = True
        ensure_payload_fits(payload, self.capabilities)
        return ChannelPresentationPayload(
            renderer_id=self.renderer_id,
            body=payload,
            fallback_text=fallback,
            degraded_to_text=degraded or omitted > 0,
            omitted_visuals=omitted,
        )


def _teams_payload(
    body: list[dict[str, object]],
    actions: list[dict[str, object]],
) -> Mapping[str, object]:
    content: dict[str, object] = {
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


__all__ = ["TEAMS_PRESENTATION_CAPABILITIES", "TeamsPresentationRenderer"]
