"""Pure bounded Slack and Teams presentation for conversation replies."""

from __future__ import annotations

import json
from typing import Any

from fdai.shared.providers.conversation_channel import (
    AgentHandoffActivity,
    ConversationActivity,
    ConversationProgressPresentation,
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
    if response.progress_presentation is ConversationProgressPresentation.DETACHED:
        rendered = f"Background task result\n\n{rendered}"
    if response.activities:
        activity_text = (
            compact_activity_summary(response.activities[0])
            if response.progress_presentation is ConversationProgressPresentation.COMPACT
            else activity_fallback(response)
        )
        rendered = f"{activity_text}\n\nBragi: {rendered}"
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
        body["blocks"] = slack_activity_blocks(response, text)
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
    if response.progress_presentation is ConversationProgressPresentation.DETACHED:
        rendered_text = f"Background task result\n\n{rendered_text}"
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
                f"{'Query' if activity.input_kind == 'query' else 'Command'}: {activity.command}",
            )
        )
        if activity.output:
            lines.append(f"Output: {activity_output_text(activity, 1_000)}")
    return "\n".join(lines)


def slack_activity_blocks(response: OutboundResponse, answer: str) -> list[dict[str, object]]:
    if (
        response.progress_presentation is ConversationProgressPresentation.COMPACT
        and len(response.activities) == 1
    ):
        return [
            slack_section(compact_activity_summary(response.activities[0])),
            slack_section(f"*Bragi*\n{slack_escape(answer)}"),
        ]
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
        input_label = "Query" if activity.input_kind == "query" else "Command"
        blocks.append(slack_plain_section(input_label, activity.command, 2_800))
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


def slack_answer_truncated(response: OutboundResponse, answer: str) -> bool:
    """Return whether Slack clips the canonical structured answer block."""

    return bool(response.activities) and len(f"*Bragi*\n{slack_escape(answer)}") > 2_900


def teams_activity_card(response: OutboundResponse, answer: str) -> dict[str, object]:
    card, _omitted, _answer_truncated = _teams_activity_card_result(response, answer)
    return card


def teams_activity_omission_count(response: OutboundResponse, answer: str) -> int:
    """Return the activities omitted by the exact Teams card budget renderer."""

    _card, omitted, _answer_truncated = _teams_activity_card_result(response, answer)
    return omitted


def teams_answer_truncated(response: OutboundResponse, answer: str) -> bool:
    """Return whether the Teams answer block clips the canonical answer."""

    _card, _omitted, answer_truncated = _teams_activity_card_result(response, answer)
    return answer_truncated


def _teams_activity_card_result(
    response: OutboundResponse,
    answer: str,
) -> tuple[dict[str, object], int, bool]:
    if (
        response.progress_presentation is ConversationProgressPresentation.COMPACT
        and len(response.activities) == 1
    ):
        answer_block, answer_truncated = _teams_answer_block(answer, [])
        return (
            teams_card(
                [
                    {
                        "type": "TextBlock",
                        "text": compact_activity_summary(response.activities[0]),
                        "wrap": True,
                        "spacing": "Small",
                        "isSubtle": True,
                    },
                    answer_block,
                ]
            ),
            0,
            answer_truncated,
        )
    body: list[dict[str, object]] = []
    omission_reserve = (
        [teams_omission_block(len(response.activities))] if response.activities else []
    )
    answer_block, answer_truncated = _teams_answer_block(answer, omission_reserve)
    omitted = 0
    for activity in response.activities:
        activity_blocks = teams_activity_blocks(activity)
        if (
            teams_card_bytes([*body, *activity_blocks, *omission_reserve, answer_block])
            > TEAMS_CARD_MAX_BYTES
        ):
            omitted += 1
            continue
        body.extend(activity_blocks)
    if omitted:
        body.append(teams_omission_block(omitted))
    body.append(answer_block)
    return teams_card(body), omitted, answer_truncated


def _teams_answer_block(
    answer: str,
    reserved_blocks: list[dict[str, object]],
) -> tuple[dict[str, object], bool]:
    def block(text: str) -> dict[str, object]:
        return {
            "type": "TextBlock",
            "text": f"**Bragi**\n{text}",
            "wrap": True,
            "separator": True,
            "spacing": "Medium",
        }

    bounded = bounded_text(answer, TEAMS_FALLBACK_MAX_CHARS)
    answer_block = block(bounded)
    char_truncated = len(answer) > TEAMS_FALLBACK_MAX_CHARS
    if teams_card_bytes([*reserved_blocks, answer_block]) <= TEAMS_CARD_MAX_BYTES:
        return answer_block, char_truncated

    suffix = "\n[TRUNCATED]"
    low = 0
    high = min(len(answer), TEAMS_FALLBACK_MAX_CHARS - len(suffix))
    while low < high:
        midpoint = (low + high + 1) // 2
        candidate = block(f"{answer[:midpoint]}{suffix}")
        if teams_card_bytes([*reserved_blocks, candidate]) <= TEAMS_CARD_MAX_BYTES:
            low = midpoint
        else:
            high = midpoint - 1
    return block(f"{answer[:low]}{suffix}"), True


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
        {"title": "Input", "value": activity.input_kind.capitalize()},
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


def compact_activity_summary(activity: ConversationActivity) -> str:
    if isinstance(activity, AgentHandoffActivity):
        return f"{activity.from_agent} -> @{activity.to_agent}: {activity.task}"
    duration = f" - {activity.duration_ms} ms" if activity.duration_ms is not None else ""
    return f"{activity.agent} - {activity.label} [{activity.tool}{duration}]"


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
    "slack_answer_truncated",
    "slack_update_body",
    "teams_activity_omission_count",
    "teams_answer_truncated",
    "teams_message_body",
]
