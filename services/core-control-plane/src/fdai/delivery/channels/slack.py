"""Pure Slack Block Kit renderer for canonical conversation presentation."""

from __future__ import annotations

from fdai.delivery.channels.common import build_fallback_text, ensure_payload_fits, payload_size
from fdai.shared.providers.channel_presentation import (
    ChannelPresentationCapabilities,
    ChannelPresentationEnvelope,
    ChannelPresentationPayload,
)

SLACK_PRESENTATION_CAPABILITIES = ChannelPresentationCapabilities(
    profile_id="slack-block-kit-v1",
    max_text_chars=12_000,
    max_serialized_bytes=50_000,
    max_blocks=50,
    max_block_text_chars=2_900,
    max_fields=40,
    max_actions=1,
    supports_edits=True,
    supports_threads=True,
    supports_progress=True,
)


class SlackPresentationRenderer:
    """Build Block Kit JSON without credentials, HTTP, or acknowledgement."""

    renderer_id = "slack-block-kit"

    def __init__(
        self,
        capabilities: ChannelPresentationCapabilities = SLACK_PRESENTATION_CAPABILITIES,
    ) -> None:
        self.capabilities = capabilities

    def render(self, envelope: ChannelPresentationEnvelope) -> ChannelPresentationPayload:
        fallback, degraded = build_fallback_text(envelope, self.capabilities)
        blocks: list[dict[str, object]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _mrkdwn(chunk)}}
            for chunk in _chunks(fallback, self.capabilities.max_block_text_chars)
        ]
        fields_used = 0
        omitted = 0
        for section in envelope.sections:
            if len(blocks) >= self.capabilities.max_blocks:
                omitted += 1
                continue
            remaining = max(0, self.capabilities.max_fields - fields_used)
            facts = section.facts[:remaining]
            heading = f"*{_mrkdwn(section.title)}*"
            if section.description is not None:
                heading += f"\n{_mrkdwn(section.description)}"
            block: dict[str, object] = {
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
        if envelope.web_url is not None and self.capabilities.max_actions > 0:
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
        payload: dict[str, object] = {"text": fallback, "blocks": blocks}
        if payload_size(payload) > self.capabilities.max_serialized_bytes:
            omitted = max(omitted, len(envelope.sections))
            payload = {
                "text": fallback,
                "blocks": blocks[: len(_chunks(fallback, self.capabilities.max_block_text_chars))],
            }
            degraded = True
        ensure_payload_fits(payload, self.capabilities)
        return ChannelPresentationPayload(
            renderer_id=self.renderer_id,
            body=payload,
            fallback_text=fallback,
            degraded_to_text=degraded or omitted > 0,
            omitted_visuals=omitted,
        )


def _chunks(value: str, maximum: int) -> tuple[str, ...]:
    return tuple(value[index : index + maximum] for index in range(0, len(value), maximum))


def _mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["SLACK_PRESENTATION_CAPABILITIES", "SlackPresentationRenderer"]
