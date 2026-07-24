"""Vendor-neutral rich channel response contract tests."""

from __future__ import annotations

import pytest

from fdai.shared.providers.conversation_channel import (
    MAX_ACTIVITY_TOTAL_CHARS,
    MAX_MENTION_COUNT,
    MAX_STREAM_CHUNKS,
    AgentHandoffActivity,
    ChannelDeliveryOperation,
    ChannelMention,
    ConversationChannelKind,
    ConversationExecutionStatus,
    ObservedExecutionActivity,
    OutboundResponse,
    outbound_response_from_json,
    outbound_response_to_json,
)


def _response(**changes: object) -> OutboundResponse:
    values: dict[str, object] = {
        "channel_kind": ConversationChannelKind.SLACK,
        "channel_id": "channel-1",
        "in_reply_to": "message-1",
        "thread_id": "thread-1",
        "status": "ok",
        "text": "fallback reply",
    }
    values.update(changes)
    return OutboundResponse(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "operation"),
    (
        ({}, ChannelDeliveryOperation.POST),
        ({"stream_chunks": ("one", " two")}, ChannelDeliveryOperation.STREAM),
        ({"edit_message_id": "message-2"}, ChannelDeliveryOperation.EDIT),
        ({"reaction": "thumbsup"}, ChannelDeliveryOperation.REACTION),
    ),
)
def test_outbound_response_selects_one_delivery_operation(
    changes: dict[str, object],
    operation: ChannelDeliveryOperation,
) -> None:
    assert _response(**changes).operation is operation


def test_mentions_keep_opaque_target_separate_from_fallback_text() -> None:
    response = _response(
        mentions=(ChannelMention(target_id="vendor-user-1", display_text="Operator"),)
    )

    assert response.mentions[0].target_id == "vendor-user-1"
    assert response.mentions[0].display_text == "Operator"


def test_agent_activity_round_trips_through_durable_response() -> None:
    response = _response(
        activities=(
            AgentHandoffActivity(
                from_agent="Bragi",
                to_agent="Heimdall",
                task="Inspect the bounded metric evidence.",
                trace_ref="trace-example",
            ),
            ObservedExecutionActivity(
                agent="Heimdall",
                label="Query metric evidence",
                tool="query_metric",
                command="query_metric --metric Requests --window PT5M",
                status=ConversationExecutionStatus.COMPLETED,
                redacted=True,
                output='{"point_count": 2, "status": "completed"}',
                exit_code=0,
                duration_ms=42,
                authority="server_read_model",
            ),
        )
    )

    restored = outbound_response_from_json(outbound_response_to_json(response))

    assert restored.activities == response.activities


def test_outbound_response_rejects_aggregate_activity_payload_over_budget() -> None:
    oversized = tuple(
        ObservedExecutionActivity(
            agent="Heimdall",
            label=f"Read evidence {index}",
            tool="query_log",
            command="query_log --query <redacted>",
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
            output="x" * 12_000,
        )
        for index in range(4)
    )

    with pytest.raises(ValueError, match="character budget"):
        _response(activities=oversized)

    assert sum(len(activity.output) for activity in oversized) == MAX_ACTIVITY_TOTAL_CHARS


@pytest.mark.parametrize(
    "changes",
    (
        {"redacted": False},
        {"command": "Bearer secret-token"},
        {"output": "/subscriptions/00000000-0000-0000-0000-000000000000"},
    ),
)
def test_execution_activity_rejects_unredacted_or_sensitive_content(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "agent": "Heimdall",
        "label": "Query metric evidence",
        "tool": "query_metric",
        "command": "query_metric --metric Requests --window PT5M",
        "status": ConversationExecutionStatus.COMPLETED,
        "redacted": True,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        ObservedExecutionActivity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"stream_chunks": ("chunk",), "edit_message_id": "message-2"},
        {"stream_chunks": ("chunk",), "reaction": "thumbsup"},
        {"edit_message_id": "message-2", "reaction": "thumbsup"},
        {
            "reaction": "thumbsup",
            "mentions": (ChannelMention(target_id="user-1", display_text="User"),),
        },
        {"stream_chunks": ("chunk",) * (MAX_STREAM_CHUNKS + 1)},
        {
            "mentions": tuple(
                ChannelMention(target_id=f"user-{index}", display_text=f"User {index}")
                for index in range(MAX_MENTION_COUNT + 1)
            )
        },
    ),
)
def test_outbound_response_rejects_ambiguous_or_unbounded_rich_intent(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _response(**changes)
