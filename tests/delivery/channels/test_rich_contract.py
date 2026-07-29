"""Vendor-neutral rich channel response contract tests."""

from __future__ import annotations

import pytest

from fdai.shared.providers.conversation_channel import (
    MAX_ACTIVITY_TOTAL_CHARS,
    MAX_MENTION_COUNT,
    MAX_PROGRESS_UPDATES,
    MAX_STREAM_CHUNKS,
    AgentHandoffActivity,
    ChannelDeliveryOperation,
    ChannelMention,
    ChannelProgressStatus,
    ChannelProgressUpdate,
    ConversationChannelKind,
    ConversationExecutionStatus,
    ConversationProgressPresentation,
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
        progress_presentation=ConversationProgressPresentation.TIMELINE,
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
        ),
    )

    restored = outbound_response_from_json(outbound_response_to_json(response))

    assert restored.activities == response.activities
    assert restored.progress_presentation is ConversationProgressPresentation.TIMELINE


@pytest.mark.parametrize(
    ("field_name", "malformed"),
    (
        ("agent", 123),
        ("output_truncated", 1),
        ("exit_code", True),
        ("duration_ms", "42"),
        ("redacted", "true"),
    ),
)
def test_durable_activity_rejects_scalar_type_coercion(
    field_name: str,
    malformed: object,
) -> None:
    serialized = outbound_response_to_json(
        _response(
            activities=(
                ObservedExecutionActivity(
                    agent="Heimdall",
                    label="Query metric evidence",
                    tool="query_metric",
                    command="query_metric --metric <redacted>",
                    status=ConversationExecutionStatus.COMPLETED,
                    redacted=True,
                ),
            )
        )
    )
    serialized["activities"][0][field_name] = malformed

    with pytest.raises(ValueError):
        outbound_response_from_json(serialized)


@pytest.mark.parametrize(
    "started_at",
    ("2026-07-24 10:15:00", "2026/07/24T10:15:00Z", "2026-07-24T10:15:00"),
)
def test_execution_activity_rejects_non_rfc3339_timestamps(started_at: str) -> None:
    with pytest.raises(ValueError, match="RFC 3339"):
        ObservedExecutionActivity(
            agent="Heimdall",
            label="Query metric evidence",
            tool="query_metric",
            command="query_metric --metric <redacted>",
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
            started_at=started_at,
        )


def test_execution_activity_rejects_reversed_timestamps() -> None:
    with pytest.raises(ValueError, match="MUST NOT precede"):
        ObservedExecutionActivity(
            agent="Heimdall",
            label="Query metric evidence",
            tool="query_metric",
            command="query_metric --metric <redacted>",
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
            started_at="2026-07-24T10:15:01Z",
            completed_at="2026-07-24T10:15:00Z",
        )


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
        {"command": "Authorization: bearer:secret-token"},
        {"command": "Authorization=bearer_secret-token"},
        {"output": "/subscriptions/00000000-0000-0000-0000-000000000000"},
        {"label": "token=secret-token"},
        {"tool": "bearer:secret-token"},
        {"authority": "Bearer secret-token"},
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
        {
            "stream_chunks": ("chunk",),
            "progress_updates": (
                ChannelProgressUpdate(0, ChannelProgressStatus.CONFIRMED, "fallback reply", 0),
            ),
        },
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


def test_progress_updates_require_monotonic_canonical_final_snapshot() -> None:
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Query metric evidence",
        tool="query_metric",
        command="query_metric --metric <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
    )
    response = _response(
        activities=(activity,),
        progress_updates=(
            ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Checking evidence", 1),
            ChannelProgressUpdate(1, ChannelProgressStatus.CONFIRMED, "fallback reply", 1),
        ),
    )

    assert response.operation is ChannelDeliveryOperation.STREAM
    assert outbound_response_from_json(outbound_response_to_json(response)) == response

    with pytest.raises(ValueError, match="canonical response"):
        _response(
            progress_updates=(
                ChannelProgressUpdate(0, ChannelProgressStatus.CONFIRMED, "not final", 0),
            ),
        )
    with pytest.raises(ValueError, match="contiguous"):
        _response(
            progress_updates=(
                ChannelProgressUpdate(1, ChannelProgressStatus.CONFIRMED, "fallback reply", 0),
            ),
        )


def test_durable_progress_rejects_scalar_coercion() -> None:
    response = _response(
        progress_updates=(
            ChannelProgressUpdate(0, ChannelProgressStatus.CONFIRMED, "fallback reply", 0),
        ),
    )
    serialized = outbound_response_to_json(response)
    serialized["progress_updates"][0]["revision"] = True

    with pytest.raises(ValueError, match="scalar types"):
        outbound_response_from_json(serialized)


def test_progress_update_count_is_bounded_before_revision_validation() -> None:
    updates = tuple(
        ChannelProgressUpdate(
            min(index, MAX_PROGRESS_UPDATES - 1),
            (
                ChannelProgressStatus.CONFIRMED
                if index == MAX_PROGRESS_UPDATES
                else ChannelProgressStatus.RUNNING
            ),
            "fallback reply" if index == MAX_PROGRESS_UPDATES else "Checking",
            0,
        )
        for index in range(MAX_PROGRESS_UPDATES + 1)
    )

    with pytest.raises(ValueError, match="progress_updates exceeds cap"):
        _response(progress_updates=updates)
