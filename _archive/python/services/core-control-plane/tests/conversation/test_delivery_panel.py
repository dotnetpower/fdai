"""The conversation delivery panel stays GET-only, aggregate, and identifier-free."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.delivery_panel import (
    ConversationDeliveryPanel,
    LatencySummary,
    ProgressiveConversationAggregate,
    project_conversation_delivery_panel,
    summarize_latency,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    AdapterBreakerMode,
    AdapterBreakerRecord,
    ConversationDeliverySnapshot,
    OutboundDeliveryAcknowledgement,
    OutboundDeliveryAttempt,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
    new_delivery_record,
)

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _record(suffix: str) -> OutboundDeliveryRecord:
    return new_delivery_record(
        origin_ref=f"turn:{suffix}",
        principal_id="principal-example",
        scope_ref="scope-example",
        conversation_id=f"conversation-{suffix}",
        binding_id="binding-example",
        response=OutboundResponse(
            channel_kind=ConversationChannelKind.SLACK,
            channel_id="channel-example",
            in_reply_to="message-example",
            thread_id="thread-example",
            status="ok",
            text="Durable response",
        ),
        created_at=NOW,
        freshness=timedelta(minutes=15),
        retention=timedelta(days=30),
    )


def _terminal(
    suffix: str,
    *,
    state: OutboundDeliveryState,
    latency_ms: int,
    attempt_count: int = 1,
    duplicate_risk: bool = False,
) -> OutboundDeliveryRecord:
    return replace(
        _record(suffix),
        state=state,
        attempt_count=attempt_count,
        duplicate_risk=duplicate_risk,
        terminal_at=NOW + timedelta(milliseconds=latency_ms),
    )


def _snapshot() -> ConversationDeliverySnapshot:
    delivered = _terminal("a", state=OutboundDeliveryState.DELIVERED, latency_ms=100)
    retried = _terminal(
        "b",
        state=OutboundDeliveryState.DELIVERED,
        latency_ms=300,
        attempt_count=3,
    )
    ambiguous = _terminal(
        "c",
        state=OutboundDeliveryState.AMBIGUOUS,
        latency_ms=900,
        attempt_count=2,
        duplicate_risk=True,
    )
    abandoned = _terminal("d", state=OutboundDeliveryState.ABANDONED, latency_ms=1500)
    pending = _record("e")
    return ConversationDeliverySnapshot(
        deliveries=(delivered, retried, ambiguous, abandoned, pending),
        attempts=(
            OutboundDeliveryAttempt(
                attempt_id="attempt-1",
                delivery_id=delivered.delivery_id,
                sequence=1,
                worker_id="worker-1",
                started_at=NOW,
            ),
            OutboundDeliveryAttempt(
                attempt_id="attempt-2",
                delivery_id=retried.delivery_id,
                sequence=1,
                worker_id="worker-1",
                started_at=NOW,
            ),
        ),
        acknowledgements=(
            OutboundDeliveryAcknowledgement(
                delivery_id=delivered.delivery_id,
                attempt_id="attempt-1",
                provider_message_id="provider-1",
                acknowledged_at=NOW + timedelta(milliseconds=100),
            ),
        ),
        breakers=(
            AdapterBreakerRecord(
                adapter_id="slack",
                channel_kind=ConversationChannelKind.SLACK,
                mode=AdapterBreakerMode.OPEN,
                failure_timestamps=(NOW,),
                revision=2,
                updated_at=NOW,
                updated_by="operator-example",
                reason="threshold",
            ),
        ),
    )


class _Reader:
    def __init__(self, snapshot: ConversationDeliverySnapshot) -> None:
        self._snapshot = snapshot
        self.calls: list[int] = []

    async def snapshot(self, *, limit: int = 200) -> ConversationDeliverySnapshot:
        self.calls.append(limit)
        return self._snapshot

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"delivery panel MUST NOT use {name}")


def test_payload_declares_read_only_and_no_mutations() -> None:
    payload = project_conversation_delivery_panel(_snapshot())

    assert payload["read_only"] is True
    assert payload["mutations_available"] is False


def test_state_and_health_counts_are_complete() -> None:
    payload = project_conversation_delivery_panel(_snapshot())

    assert payload["state_counts"] == {
        "pending": 1,
        "sending": 0,
        "delivered": 2,
        "ambiguous": 1,
        "failed": 0,
        "abandoned": 1,
    }
    assert payload["duplicate_risk_count"] == 1
    assert payload["retry_count"] == 3
    assert payload["abandoned_count"] == 1
    assert payload["attempt_count"] == 2
    assert payload["acknowledgement_count"] == 1
    assert payload["breaker_state_counts"] == {"closed": 0, "open": 1, "paused": 0}


def test_latency_uses_terminal_deliveries_only() -> None:
    payload = project_conversation_delivery_panel(_snapshot())
    latency = payload["delivery_latency"]

    assert isinstance(latency, dict)
    assert latency["count"] == 4
    assert latency["average_ms"] == pytest.approx(700.0)
    assert latency["p95_ms"] == pytest.approx(1500.0)


def test_payload_exposes_no_identifier_or_answer_text() -> None:
    rendered = json.dumps(project_conversation_delivery_panel(_snapshot()))

    for forbidden in (
        "principal-example",
        "conversation-a",
        "channel-example",
        "Durable response",
        "provider-1",
        "operator-example",
        "slack",
    ):
        assert forbidden not in rendered


def test_progressive_counters_are_optional() -> None:
    assert project_conversation_delivery_panel(_snapshot())["progressive"] is None

    payload = project_conversation_delivery_panel(
        _snapshot(),
        progressive=ProgressiveConversationAggregate(
            conversation_count=2,
            first_progress=summarize_latency([120.0, 180.0]),
            first_confirmed=summarize_latency([400.0]),
            branch=summarize_latency([]),
        ),
    )
    progressive = payload["progressive"]

    assert isinstance(progressive, dict)
    assert progressive["conversation_count"] == 2
    assert progressive["branch_latency"] == {"count": 0, "average_ms": None, "p95_ms": None}


async def test_panel_reads_without_touching_a_mutation_path() -> None:
    reader = _Reader(_snapshot())

    payload = await ConversationDeliveryPanel(reader=reader, limit=50).read()

    assert reader.calls == [50]
    assert payload["mutations_available"] is False


def test_panel_limit_is_bounded() -> None:
    reader = _Reader(_snapshot())

    for invalid in (0, -1, 1001):
        with pytest.raises(ValueError, match="limit MUST be"):
            ConversationDeliveryPanel(reader=reader, limit=invalid)


def test_empty_snapshot_reports_unavailable_percentiles() -> None:
    payload = project_conversation_delivery_panel(
        ConversationDeliverySnapshot(deliveries=(), attempts=(), acknowledgements=(), breakers=())
    )

    assert payload["delivery_latency"] == {"count": 0, "average_ms": None, "p95_ms": None}
    assert payload["delivery_count"] == 0


def test_latency_samples_must_be_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        summarize_latency([float("nan")])
    with pytest.raises(ValueError, match="finite"):
        summarize_latency([-1.0])


def test_summary_percentile_uses_nearest_rank() -> None:
    summary = summarize_latency([float(value) for value in range(1, 21)])

    assert summary == LatencySummary(count=20, average_ms=10.5, p95_ms=19.0)


def test_progressive_counts_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="NOT be negative"):
        ProgressiveConversationAggregate(
            conversation_count=-1,
            first_progress=summarize_latency([]),
            first_confirmed=summarize_latency([]),
            branch=summarize_latency([]),
        )
