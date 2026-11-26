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
    OutboundDeliveryOriginDeletedError,
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


def test_delivery_record_carries_its_origin_reference() -> None:
    record = _record()

    assert record.origin_ref == "turn:example"
    assert delivery_record_to_json(record)["origin_ref"] == "turn:example"


async def test_origin_deletion_removes_bodies_and_retains_lineage() -> None:
    store = InMemoryConversationDeliveryStore()
    record = await store.put(_record())
    claimed = await store.claim(
        delivery_id=record.delivery_id, now=NOW, worker_id="worker-a", lease_seconds=30
    )
    assert claimed is not None
    await store.finish(
        delivery_id=record.delivery_id,
        worker_id="worker-a",
        expected_attempt_count=1,
        state=OutboundDeliveryState.DELIVERED,
        at=NOW,
        acknowledgement=OutboundDeliveryAcknowledgement(
            delivery_id=record.delivery_id,
            attempt_id=f"{record.delivery_id}:attempt:1",
            provider_message_id="provider-message-example",
            acknowledged_at=NOW,
        ),
    )

    result = await store.delete_by_origin(origin_ref="turn:example", at=NOW)

    assert result.deleted_delivery_ids == (record.delivery_id,)
    assert result.retained_attempts == 1
    assert result.retained_acknowledgements == 1
    assert await store.get(record.delivery_id) is None
    snapshot = await store.snapshot()
    assert snapshot.deliveries == ()
    assert snapshot.acknowledgements[0].provider_message_id == "provider-message-example"


async def test_origin_deletion_preserves_unrelated_origins() -> None:
    store = InMemoryConversationDeliveryStore()
    kept = await store.put(replace_origin(_record(), "turn:other"))
    await store.put(_record())

    result = await store.delete_by_origin(origin_ref="turn:example", at=NOW)

    assert result.deleted_delivery_ids != ()
    assert await store.get(kept.delivery_id) == kept


async def test_purged_origin_refuses_a_resigned_replay() -> None:
    store = InMemoryConversationDeliveryStore()
    record = _record()
    await store.put(record)
    await store.delete_by_origin(origin_ref="turn:example", at=NOW)

    resigned = replace(
        record,
        delivery_id="delivery:resigned",
        idempotency_key="resigned-key",
        response=replace(record.response, text="Durable response"),
    )
    with pytest.raises(OutboundDeliveryOriginDeletedError):
        await store.put(record)
    with pytest.raises(OutboundDeliveryOriginDeletedError):
        await store.put(resigned)


async def test_origin_deletion_rejects_unbounded_or_naive_input() -> None:
    store = InMemoryConversationDeliveryStore()

    with pytest.raises(ValueError, match="origin_ref"):
        await store.delete_by_origin(origin_ref="  ", at=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.delete_by_origin(origin_ref="turn:example", at=NOW.replace(tzinfo=None))


def replace_origin(record: OutboundDeliveryRecord, origin_ref: str) -> OutboundDeliveryRecord:
    """Rebuild one record under another origin without touching its response body."""
    return new_delivery_record(
        origin_ref=origin_ref,
        principal_id=record.principal_id,
        scope_ref=record.scope_ref,
        conversation_id=record.conversation_id,
        binding_id=record.binding_id,
        response=record.response,
        created_at=record.created_at,
        freshness=record.expires_at - record.created_at,
        retention=record.retention_until - record.created_at,
    )
