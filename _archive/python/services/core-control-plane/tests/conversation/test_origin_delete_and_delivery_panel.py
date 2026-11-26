"""Tests for origin-scoped outbound delivery deletion and delivery panel projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.delivery_panel import (
    ConversationDeliveryPanel,
    ProgressiveConversationAggregate,
    summarize_latency,
)
from fdai.core.scheduler.continuation_retention import InMemoryContinuationDeletionFence
from fdai.delivery.outbound_delivery_origin_delete import (
    InMemoryOriginDeletionAuditSink,
    OriginDeletionPreconditionError,
    OriginScopedOutboundDeliveryDeleter,
)
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
    new_delivery_record,
)

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _record(
    *,
    origin_ref: str,
    conversation_id: str,
    channel_id: str = "chan-ops",
    text: str = "Scheduled result body",
) -> OutboundDeliveryRecord:
    return new_delivery_record(
        origin_ref=origin_ref,
        principal_id="principal-ops-1",
        scope_ref="scope:prod",
        conversation_id=conversation_id,
        binding_id="binding-ops-1",
        response=OutboundResponse(
            channel_kind=ConversationChannelKind.SLACK,
            channel_id=channel_id,
            in_reply_to=origin_ref,
            thread_id="thread-ops-1",
            status="ok",
            text=text,
        ),
        created_at=NOW,
        freshness=timedelta(minutes=15),
        retention=timedelta(days=7),
    )


async def test_origin_scoped_deleter_purges_anchor_preserves_lineage_and_replays_idempotently() -> (
    None
):
    store = InMemoryConversationDeliveryStore()
    audit = InMemoryOriginDeletionAuditSink()
    fence = InMemoryContinuationDeletionFence()
    deleter = OriginScopedOutboundDeliveryDeleter(
        store=store,
        audit=audit,
        fence=fence,
        clock=lambda: NOW + timedelta(minutes=5),
    )

    doomed = await store.put(_record(origin_ref="anchor:run-1", conversation_id="session-1"))
    claimed = await store.claim(
        delivery_id=doomed.delivery_id,
        now=NOW + timedelta(seconds=1),
        worker_id="worker-1",
        lease_seconds=30,
    )
    assert claimed is not None
    await store.finish(
        delivery_id=doomed.delivery_id,
        worker_id="worker-1",
        expected_attempt_count=1,
        state=OutboundDeliveryState.DELIVERED,
        at=NOW + timedelta(seconds=2),
        acknowledgement=OutboundDeliveryAcknowledgement(
            delivery_id=doomed.delivery_id,
            attempt_id=f"{doomed.delivery_id}:attempt:1",
            provider_message_id="slack-msg-1",
            acknowledged_at=NOW + timedelta(seconds=2),
        ),
    )
    survivor = await store.put(_record(origin_ref="anchor:run-2", conversation_id="session-2"))

    # Refuses scheduled-continuation purge when fence is not recorded yet.
    with pytest.raises(OriginDeletionPreconditionError, match="deletion fence"):
        await deleter.purge_origin(
            origin_id="anchor:run-1",
            actor_id="system:retention",
            reason="scheduled_result_expired",
            require_fence=True,
        )

    await fence.record(anchor_id="anchor:run-1", at=NOW + timedelta(minutes=4))
    first_receipt = await deleter.purge_origin(
        origin_id="anchor:run-1",
        session_id="session-1",
        actor_id="system:retention",
        reason="scheduled_result_expired",
        require_fence=True,
    )

    assert first_receipt.execution_authority == "none"
    assert first_receipt.fence_verified is True
    assert first_receipt.idempotent_replay is False
    assert first_receipt.deleted_delivery_ids == (doomed.delivery_id,)
    assert first_receipt.retained_attempts == 1
    assert first_receipt.retained_acknowledgements == 1
    assert first_receipt.receipt_digest.startswith("sha256:")
    assert await store.get(doomed.delivery_id) is None
    assert await store.get(survivor.delivery_id) is not None

    # Idempotent replay succeeds with empty deleted_delivery_ids and idempotent_replay=True.
    replay_receipt = await deleter.purge_origin(
        origin_id="anchor:run-1",
        session_id="session-1",
        actor_id="system:retention",
        reason="scheduled_result_expired",
        require_fence=True,
    )
    assert replay_receipt.idempotent_replay is True
    assert replay_receipt.deleted_delivery_ids == ()
    assert replay_receipt.retained_attempts == 0
    assert len(audit.receipts) == 2

    # Late writer attempting to restore the purged origin is blocked by the tombstone.
    with pytest.raises(OutboundDeliveryOriginDeletedError):
        await store.put(
            _record(
                origin_ref="anchor:run-1",
                conversation_id="session-1",
                channel_id="chan-other",
            )
        )


async def test_session_scoped_purge_removes_all_bound_origins_and_preserves_other_sessions() -> (
    None
):
    store = InMemoryConversationDeliveryStore()
    audit = InMemoryOriginDeletionAuditSink()
    deleter = OriginScopedOutboundDeliveryDeleter(
        store=store,
        audit=audit,
        clock=lambda: NOW + timedelta(minutes=10),
    )

    first = await store.put(_record(origin_ref="turn:1", conversation_id="session-alpha"))
    second = await store.put(_record(origin_ref="turn:2", conversation_id="session-alpha"))
    other = await store.put(_record(origin_ref="turn:3", conversation_id="session-beta"))

    receipts = await deleter.purge_session(
        session_id="session-alpha",
        actor_id="operator:owner-1",
        reason="conversation_deleted",
    )
    assert len(receipts) == 2
    assert {r.origin_id for r in receipts} == {"turn:1", "turn:2"}
    assert all(r.session_id == "session-alpha" for r in receipts)
    assert all(r.execution_authority == "none" for r in receipts)
    assert await store.get(first.delivery_id) is None
    assert await store.get(second.delivery_id) is None
    assert await store.get(other.delivery_id) is not None

    replay_receipts = await deleter.purge_session(
        session_id="session-alpha",
        actor_id="operator:owner-1",
        reason="conversation_deleted",
    )
    assert len(replay_receipts) == 2
    assert all(r.idempotent_replay is True for r in replay_receipts)


async def test_delivery_panel_reads_post_purge_snapshot_without_identifiers() -> None:
    store = InMemoryConversationDeliveryStore()
    audit = InMemoryOriginDeletionAuditSink()
    deleter = OriginScopedOutboundDeliveryDeleter(
        store=store,
        audit=audit,
        clock=lambda: NOW + timedelta(minutes=2),
    )

    purged = await store.put(
        _record(
            origin_ref="turn:secret-origin",
            conversation_id="session-secret",
            text="Sensitive body that must be purged",
        )
    )
    retained = await store.put(
        _record(
            origin_ref="turn:active-origin",
            conversation_id="session-active",
            text="Active body that must never appear in panel",
        )
    )
    assert purged.delivery_id != retained.delivery_id

    await deleter.purge_origin(
        origin_id="turn:secret-origin",
        actor_id="operator:owner-1",
        reason="origin_purged",
    )

    panel = ConversationDeliveryPanel(reader=store, limit=50)
    progressive = ProgressiveConversationAggregate(
        conversation_count=3,
        first_progress=summarize_latency([120.0, 180.0, 240.0]),
        first_confirmed=summarize_latency([450.0, 600.0, 750.0]),
        branch=summarize_latency([80.0, 110.0]),
    )
    payload = await panel.read(progressive=progressive)

    assert payload["read_only"] is True
    assert payload["mutations_available"] is False
    assert payload["delivery_count"] == 1
    assert payload["progressive"] is not None

    encoded = json.dumps(payload)
    for forbidden in (
        "turn:secret-origin",
        "turn:active-origin",
        "session-secret",
        "session-active",
        "principal-ops-1",
        "Sensitive body",
        "Active body",
    ):
        assert forbidden not in encoded


async def test_origin_scoped_deleter_rejects_invalid_identifiers_and_naive_timestamps() -> None:
    store = InMemoryConversationDeliveryStore()
    audit = InMemoryOriginDeletionAuditSink()
    deleter = OriginScopedOutboundDeliveryDeleter(store=store, audit=audit, clock=lambda: NOW)

    with pytest.raises(ValueError, match="origin_id MUST be non-empty"):
        await deleter.purge_origin(origin_id="   ", actor_id="operator:1", reason="cleanup")

    with pytest.raises(ValueError, match="reason MUST be non-empty"):
        await deleter.purge_origin(origin_id="turn:1", actor_id="operator:1", reason="   ")

    with pytest.raises(ValueError, match="timezone-aware"):
        await deleter.purge_origin(
            origin_id="turn:1",
            actor_id="operator:1",
            reason="cleanup",
            at=datetime(2026, 11, 1, 9, 0),
        )
