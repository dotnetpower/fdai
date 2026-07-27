"""Pure bounded Slack and Teams presentation for conversation replies."""

from __future__ import annotations

import json
from typing import Any

from fdai.shared.providers.conversation_channel import (
    AgentHandoffActivity,
    ConversationActivity,
    ObservedExecutionActivity,
    OutboundResponse,
)

TEAMS_CARD_MAX_BYTES = 24_000
TEAMS_FALLBACK_MAX_CHARS = 4_000


def render_slack_text(
    response: OutboundResponse,
    text: str,
    *,
    native_mentions: bool,
    include_operation_fallback: bool = False,
) -> str:
    mention_text = " ".join(
        f"<@{mention.target_id}>" if native_mentions else f"@{mention.display_text}"
        for mention in response.mentions
    )
    rendered = f"{mention_text} {text}" if mention_text else text
    if response.activities:
        rendered = f"{activity_fallback(response)}\n\nBragi: {rendered}"
    if include_operation_fallback and response.reaction is not None:
        rendered = f"{rendered}\n\nReaction: {response.reaction}"
    elif include_operation_fallback and response.edit_message_id is not None:
        rendered = f"Update: {rendered}"
    return rendered


def slack_update_body(
    response: OutboundResponse,
    *,
    message_id: str,
    text: str,
    native_mentions: bool,
) -> dict[str, object]:
    rendered = render_slack_text(response, text, native_mentions=native_mentions)
    body: dict[str, object] = {
        "channel": response.channel_id,
        "ts": message_id,
        "text": rendered,
    }
    if response.activities:
        body["blocks"] = slack_activity_blocks(response, rendered)
    return body


def operation_fallback_text(response: OutboundResponse) -> str:
    text = response.text
    if response.reaction is not None:
        text = f"{text}\n\nReaction: {response.reaction}"
    elif response.edit_message_id is not None:
        text = f"Update: {text}"
    return text


def teams_message_body(
    response: OutboundResponse,
    text: str,
    *,
    native_mentions: bool,
) -> dict[str, Any]:
    rendered_text = (
        bounded_text(
            f"{activity_fallback(response)}\n\nBragi: {text}",
            TEAMS_FALLBACK_MAX_CHARS,
        )
        if response.activities
        else text
    )
    body: dict[str, Any] = {"type": "message", "text": rendered_text}
    if response.activities:
        body["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": teams_activity_card(response, text),
            }
        ]
    if not response.mentions:
        return body
    if not native_mentions:
        mention_text = " ".join(f"@{mention.display_text}" for mention in response.mentions)
        body["text"] = f"{mention_text} {rendered_text}"
        return body
    tags = [f"<at>{mention.display_text}</at>" for mention in response.mentions]
    body["text"] = f"{' '.join(tags)} {rendered_text}"
    body["entities"] = [
        {
            "type": "mention",
            "text": tag,
            "mentioned": {"id": mention.target_id, "name": mention.display_text},
        }
        for tag, mention in zip(tags, response.mentions, strict=True)
    ]
    return body


def activity_fallback(response: OutboundResponse) -> str:
    lines: list[str] = []
    for activity in response.activities:
        if isinstance(activity, AgentHandoffActivity):
            lines.append(f"{activity.from_agent} -> @{activity.to_agent}: {activity.task}")
            continue
        status = activity.status.value.capitalize()
        lines.extend(
            (
                f"{activity.agent} - {activity.label} [{status}]",
                f"Command: {activity.command}",
            )
        )
        if activity.output:
            lines.append(f"Output: {activity_output_text(activity, 1_000)}")
    return "\n".join(lines)


def slack_activity_blocks(response: OutboundResponse, answer: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for activity in response.activities:
        if isinstance(activity, AgentHandoffActivity):
            blocks.append(
                slack_section(
                    f"*{slack_escape(activity.from_agent)}* -> "
                    f"*@{slack_escape(activity.to_agent)}*\n"
                    f"{slack_escape(activity.task)}"
                )
            )
            continue
        blocks.append(
            slack_section(
                f"*{slack_escape(activity.agent)} - {slack_escape(activity.label)}* "
                f"`{activity.status.value}`\n"
                f"*{slack_escape(activity.tool)}*"
            )
        )
        blocks.append(slack_plain_section("Command", activity.command, 2_800))
        if activity.output:
            blocks.append(
                slack_plain_section("Output", activity_output_text(activity, 2_800), 2_800)
            )
    blocks.append(slack_section(f"*Bragi*\n{slack_escape(answer)}"))
    return blocks


def slack_section(text: str) -> dict[str, object]:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": bounded_text(text, 2_900)},
    }


def slack_plain_section(title: str, value: str, limit: int) -> dict[str, object]:
    return {
        "type": "section",
        "text": {
            "type": "plain_text",
            "text": f"{title}\n{bounded_text(value, limit)}",
        },
    }


def slack_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def teams_activity_card(response: OutboundResponse, answer: str) -> dict[str, object]:
    body: list[dict[str, object]] = []
    answer_block: dict[str, object] = {
        "type": "TextBlock",
        "text": f"**Bragi**\n{bounded_text(answer, 4_000)}",
        "wrap": True,
        "separator": True,
        "spacing": "Medium",
    }
    omitted = 0
    for activity in response.activities:
        activity_blocks = teams_activity_blocks(activity)
        if (
            teams_card_bytes([*body, *activity_blocks, teams_omission_block(1), answer_block])
            > TEAMS_CARD_MAX_BYTES
        ):
            omitted += 1
            continue
        body.extend(activity_blocks)
    if omitted:
        body.append(teams_omission_block(omitted))
    body.append(answer_block)
    return teams_card(body)


def teams_activity_blocks(activity: ConversationActivity) -> list[dict[str, object]]:
    if isinstance(activity, AgentHandoffActivity):
        return [
            {
                "type": "TextBlock",
                "text": f"**{activity.from_agent}** -> **@{activity.to_agent}**\n{activity.task}",
                "wrap": True,
                "spacing": "Small",
            }
        ]
    facts: list[dict[str, str]] = [
        {"title": "Status", "value": activity.status.value.capitalize()},
        {"title": "Tool", "value": activity.tool},
    ]
    if activity.authority:
        facts.append({"title": "Authority", "value": activity.authority})
    if activity.exit_code is not None:
        facts.append({"title": "Exit code", "value": str(activity.exit_code)})
    blocks: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "text": f"**{activity.agent} - {activity.label}**",
            "wrap": True,
            "spacing": "Medium",
        },
        {"type": "FactSet", "facts": facts},
        {
            "type": "TextBlock",
            "text": bounded_text(activity.command, 4_000),
            "fontType": "Monospace",
            "wrap": True,
            "separator": True,
        },
    ]
    if activity.output:
        blocks.append(
            {
                "type": "TextBlock",
                "text": activity_output_text(activity, 4_000),
                "fontType": "Monospace",
                "wrap": True,
                "separator": True,
            }
        )
    return blocks


def teams_omission_block(count: int) -> dict[str, object]:
    noun = "activity" if count == 1 else "activities"
    return {
        "type": "TextBlock",
        "text": f"{count} additional {noun} omitted by Teams limit.",
        "wrap": True,
        "isSubtle": True,
        "separator": True,
    }


def teams_card(body: list[dict[str, object]]) -> dict[str, object]:
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
    }


def teams_card_bytes(body: list[dict[str, object]]) -> int:
    return len(json.dumps(teams_card(body), separators=(",", ":")).encode("utf-8"))


def bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    suffix = "\n[TRUNCATED]"
    return f"{value[: max(0, limit - len(suffix))]}{suffix}"


def activity_output_text(activity: ObservedExecutionActivity, limit: int) -> str:
    markers = ["[UPSTREAM OUTPUT TRUNCATED]"] if activity.output_truncated else []
    marker_suffix = "" if not markers else f"\n{' '.join(markers)}"
    if len(activity.output) + len(marker_suffix) <= limit:
        return f"{activity.output}{marker_suffix}"
    markers.append("[CHANNEL OUTPUT TRUNCATED]")
    suffix = f"\n{' '.join(markers)}"
    return f"{activity.output[: max(0, limit - len(suffix))]}{suffix}"


__all__ = [
    "operation_fallback_text",
    "render_slack_text",
    "slack_activity_blocks",
    "slack_update_body",
    "teams_message_body",
]
