from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryAcknowledgement,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
    delivery_record_from_json,
    delivery_record_to_json,
    new_delivery_record,
    response_digest,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _record() -> OutboundDeliveryRecord:
    return new_delivery_record(
        origin_ref="turn:example",
        principal_id="principal-example",
        scope_ref="scope-example",
        conversation_id="conversation-example",
        binding_id="binding-example",
        response=OutboundResponse(
            channel_kind=ConversationChannelKind.SLACK,
            channel_id="channel-example",
            in_reply_to="message-example",
            thread_id="thread-example",
            status="ok",
            text="Durable response",
            data={"answer": 42},
            evidence_refs=("audit:example",),
        ),
        created_at=NOW,
        freshness=timedelta(minutes=15),
        retention=timedelta(days=30),
    )


def test_delivery_record_round_trip_preserves_complete_response() -> None:
    record = _record()
    assert delivery_record_from_json(delivery_record_to_json(record)) == record


async def test_idempotent_put_and_single_compare_and_set_claim() -> None:
    store = InMemoryConversationDeliveryStore()
    record = _record()
    assert await store.put(record) == record
    assert await store.put(record) == record

    first = await store.claim_due(now=NOW, worker_id="worker-a", lease_seconds=30, limit=1)
    second = await store.claim_due(now=NOW, worker_id="worker-b", lease_seconds=30, limit=1)

    assert len(first) == 1
    assert second == ()
    assert first[0].state is OutboundDeliveryState.SENDING
    assert first[0].attempt_count == 1


async def test_stale_sending_lease_reconciles_to_visible_ambiguous_terminal() -> None:
    store = InMemoryConversationDeliveryStore()
    record = await store.put(_record())
    await store.claim_due(now=NOW, worker_id="worker-a", lease_seconds=30, limit=1)

    assert await store.reconcile_sending(now=NOW + timedelta(seconds=31)) == 1
    reconciled = await store.get(record.delivery_id)
    assert reconciled is not None
    assert reconciled.state is OutboundDeliveryState.AMBIGUOUS
    assert reconciled.duplicate_risk is True
    assert reconciled.last_error_code == "process_loss"


async def test_delivered_terminal_is_immutable_and_acknowledged() -> None:
    store = InMemoryConversationDeliveryStore()
    record = await store.put(_record())
    claimed = (
        await store.claim_due(
            now=NOW,
            worker_id="worker-a",
            lease_seconds=30,
            limit=1,
        )
    )[0]
    acknowledgement = OutboundDeliveryAcknowledgement(
        delivery_id=record.delivery_id,
        attempt_id=f"{record.delivery_id}:attempt:1",
        provider_message_id="provider-message-example",
        acknowledged_at=NOW + timedelta(seconds=1),
    )
    delivered = await store.finish(
        delivery_id=record.delivery_id,
        worker_id="worker-a",
        expected_attempt_count=claimed.attempt_count,
        state=OutboundDeliveryState.DELIVERED,
        at=NOW + timedelta(seconds=1),
        acknowledgement=acknowledgement,
    )
    assert delivered.state is OutboundDeliveryState.DELIVERED
    assert (await store.snapshot()).acknowledgements == (acknowledgement,)

    with pytest.raises(ValueError, match="immutable"):
        await store.finish(
            delivery_id=record.delivery_id,
            worker_id="worker-a",
            expected_attempt_count=1,
            state=OutboundDeliveryState.FAILED,
            at=NOW + timedelta(seconds=2),
            next_due_at=NOW + timedelta(seconds=3),
        )


async def test_same_idempotency_key_cannot_change_stored_response() -> None:
    store = InMemoryConversationDeliveryStore()
    record = await store.put(_record())
    changed_response = replace(record.response, text="Different response")
    changed = replace(
        record,
        response=changed_response,
        response_digest=response_digest(changed_response),
    )
    with pytest.raises(ValueError, match="different response"):
        await store.put(changed)
