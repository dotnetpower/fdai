"""Live PostgreSQL checks for Operator-owned outbound channel delivery."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelBreakerMode,
    ChannelDeliveryAcknowledgement,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    ChannelKind,
    PrincipalChannelBinding,
    VerifiedChannelEndpoint,
    channel_response_digest,
)
from fdai_operator_service.families.conversation.postgres_channel_binding import (
    PostgresChannelBindingConfig,
    PostgresPrincipalChannelBindingStore,
)
from fdai_operator_service.families.conversation.postgres_channel_delivery import (
    PostgresChannelDeliveryConfig,
    PostgresChannelDeliveryStore,
)

_NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _binding(suffix: str) -> PrincipalChannelBinding:
    principal_id = f"delivery-principal-{suffix}"
    scope_ref = f"scope://delivery/{suffix}"
    return PrincipalChannelBinding(
        binding_id=f"delivery-binding-{suffix}",
        principal_id=principal_id,
        scope_ref=scope_ref,
        conversation_id=f"delivery-conversation-{suffix}",
        endpoint=VerifiedChannelEndpoint(
            principal_id=principal_id,
            scope_ref=scope_ref,
            channel_kind=ChannelKind.TEAMS,
            channel_id=f"delivery-channel-{suffix}",
            sender_id=f"delivery-sender-{suffix}",
            thread_id=None,
            verification_ref=f"delivery-verification-{suffix}",
            verified_at=_NOW,
        ),
        created_by="operator-channel-edge",
        created_at=_NOW,
    )


def _record(
    binding: PrincipalChannelBinding,
    *,
    suffix: str,
    due_at: datetime = _NOW,
    retention_until: datetime | None = None,
) -> ChannelDeliveryRecord:
    response = {
        "answer": f"Verified response {suffix}",
        "status": "answered",
        "verification": {
            "status": "verified",
            "evidence_refs": [f"audit:{suffix}"],
        },
        "execution_authority": False,
    }
    expires_at = _NOW + timedelta(minutes=10)
    return ChannelDeliveryRecord(
        delivery_id=f"delivery-{suffix}",
        idempotency_key=f"channel-delivery:{suffix}",
        principal_id=binding.principal_id,
        scope_ref=binding.scope_ref,
        conversation_id=binding.conversation_id,
        binding_id=binding.binding_id,
        channel_kind=binding.endpoint.channel_kind,
        response=response,
        response_digest=channel_response_digest(response),
        state=ChannelDeliveryState.PENDING,
        created_at=_NOW,
        due_at=due_at,
        expires_at=expires_at,
        retention_until=retention_until or _NOW + timedelta(days=1),
    )


async def _stores() -> tuple[
    str,
    str,
    PostgresPrincipalChannelBindingStore,
    PostgresChannelDeliveryStore,
]:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    return (
        admin_dsn,
        operator_dsn,
        PostgresPrincipalChannelBindingStore(config=PostgresChannelBindingConfig(dsn=operator_dsn)),
        PostgresChannelDeliveryStore(config=PostgresChannelDeliveryConfig(dsn=operator_dsn)),
    )


async def _cleanup(admin_dsn: str, binding: PrincipalChannelBinding) -> None:
    async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
        await connection.execute(
            "DELETE FROM conversation_outbound_delivery WHERE binding_id = %s",
            (binding.binding_id,),
        )
        await connection.execute(
            "DELETE FROM principal_conversation_binding WHERE binding_id = %s",
            (binding.binding_id,),
        )
        await connection.commit()


@pytest.mark.integration
async def test_operator_delivery_put_is_exactly_idempotent() -> None:
    admin_dsn, _operator_dsn, binding_store, delivery_store = await _stores()
    suffix = uuid4().hex
    binding = _binding(suffix)
    record = _record(binding, suffix=suffix)
    try:
        await binding_store.create(binding)
        assert await delivery_store.put(record) == record
        assert await delivery_store.put(record) == record
        changed_response = dict(record.response)
        changed_response["answer"] = "Different response"
        conflict = replace(
            record,
            delivery_id=f"delivery-conflict-{suffix}",
            response=changed_response,
            response_digest=channel_response_digest(changed_response),
        )
        with pytest.raises(ValueError, match="conflicts with different content"):
            await delivery_store.put(conflict)
    finally:
        await _cleanup(admin_dsn, binding)


@pytest.mark.integration
async def test_operator_delivery_claim_ack_and_terminal_guard_are_atomic() -> None:
    admin_dsn, operator_dsn, binding_store, delivery_store = await _stores()
    suffix = uuid4().hex
    binding = _binding(suffix)
    record = _record(binding, suffix=suffix)
    try:
        await binding_store.create(binding)
        await delivery_store.put(record)
        claimed = await delivery_store.claim(
            delivery_id=record.delivery_id,
            now=_NOW,
            worker_id="channel-worker",
            lease_seconds=30,
        )
        assert claimed is not None and claimed.attempt_count == 1
        assert (
            await delivery_store.claim(
                delivery_id=record.delivery_id,
                now=_NOW,
                worker_id="other-worker",
                lease_seconds=30,
            )
            is None
        )
        acknowledgement = ChannelDeliveryAcknowledgement(
            delivery_id=record.delivery_id,
            attempt_id=f"{record.delivery_id}:attempt:1",
            provider_message_id=f"provider-{suffix}",
            acknowledged_at=_NOW + timedelta(seconds=1),
        )
        delivered = await delivery_store.finish(
            delivery_id=record.delivery_id,
            worker_id="channel-worker",
            expected_attempt_count=1,
            state=ChannelDeliveryState.DELIVERED,
            at=_NOW + timedelta(seconds=1),
            acknowledgement=acknowledgement,
        )
        assert delivered.state is ChannelDeliveryState.DELIVERED
        snapshot = await delivery_store.snapshot(limit=500)
        attempts = [item for item in snapshot.attempts if item.delivery_id == record.delivery_id]
        acknowledgements = [
            item for item in snapshot.acknowledgements if item.delivery_id == record.delivery_id
        ]
        assert len(attempts) == 1 and attempts[0].outcome is ChannelDeliveryState.DELIVERED
        assert acknowledgements == [acknowledgement]

        async with await psycopg.AsyncConnection.connect(operator_dsn) as connection:
            with pytest.raises(psycopg.errors.RaiseException, match="terminal.*immutable"):
                await connection.execute(
                    "UPDATE conversation_outbound_delivery SET response = %s::jsonb "
                    "WHERE delivery_id = %s",
                    ('{"answer":"mutated"}', record.delivery_id),
                )
    finally:
        await _cleanup(admin_dsn, binding)


@pytest.mark.integration
async def test_operator_delivery_retry_and_process_loss_are_fenced() -> None:
    admin_dsn, _operator_dsn, binding_store, delivery_store = await _stores()
    suffix = uuid4().hex
    binding = _binding(suffix)
    retry_record = _record(binding, suffix=f"retry-{suffix}")
    lost_record = _record(binding, suffix=f"lost-{suffix}")
    try:
        await binding_store.create(binding)
        await delivery_store.put(retry_record)
        await delivery_store.put(lost_record)
        retry_claim = await delivery_store.claim(
            delivery_id=retry_record.delivery_id,
            now=_NOW,
            worker_id="retry-worker",
            lease_seconds=30,
        )
        lost_claim = await delivery_store.claim(
            delivery_id=lost_record.delivery_id,
            now=_NOW,
            worker_id="lost-worker",
            lease_seconds=30,
        )
        assert retry_claim is not None and lost_claim is not None
        failed = await delivery_store.finish(
            delivery_id=retry_record.delivery_id,
            worker_id="retry-worker",
            expected_attempt_count=1,
            state=ChannelDeliveryState.FAILED,
            at=_NOW + timedelta(seconds=1),
            next_due_at=_NOW + timedelta(seconds=5),
            error_code="provider_rejected",
        )
        assert failed.state is ChannelDeliveryState.FAILED
        early = await delivery_store.claim_due(
            now=_NOW + timedelta(seconds=4),
            worker_id="due-worker",
            lease_seconds=30,
            limit=200,
        )
        assert all(item.delivery_id != retry_record.delivery_id for item in early)
        due = await delivery_store.claim_due(
            now=_NOW + timedelta(seconds=5),
            worker_id="due-worker",
            lease_seconds=30,
            limit=200,
        )
        retry_due = [item for item in due if item.delivery_id == retry_record.delivery_id]
        assert len(retry_due) == 1 and retry_due[0].attempt_count == 2
        assert await delivery_store.reconcile_sending(now=_NOW + timedelta(seconds=31)) >= 1
        lost = await delivery_store.get(lost_record.delivery_id)
        assert lost is not None
        assert lost.state is ChannelDeliveryState.AMBIGUOUS
        assert lost.duplicate_risk is True and lost.last_error_code == "process_loss"
    finally:
        await _cleanup(admin_dsn, binding)


@pytest.mark.integration
async def test_operator_breaker_cas_and_terminal_retention_cleanup() -> None:
    admin_dsn, _operator_dsn, binding_store, delivery_store = await _stores()
    suffix = uuid4().hex
    binding = _binding(suffix)
    record = _record(
        binding,
        suffix=suffix,
        retention_until=_NOW + timedelta(minutes=11),
    )
    adapter_id = f"adapter-{suffix}"
    breaker = ChannelAdapterBreaker(
        adapter_id=adapter_id,
        channel_kind=ChannelKind.TEAMS,
        mode=ChannelBreakerMode.CLOSED,
        revision=0,
        updated_at=_NOW,
        updated_by="operator-channel-edge",
        reason="initialized",
    )
    try:
        await binding_store.create(binding)
        await delivery_store.put(record)
        claimed = await delivery_store.claim(
            delivery_id=record.delivery_id,
            now=_NOW,
            worker_id="cleanup-worker",
            lease_seconds=30,
        )
        assert claimed is not None
        await delivery_store.finish(
            delivery_id=record.delivery_id,
            worker_id="cleanup-worker",
            expected_attempt_count=1,
            state=ChannelDeliveryState.ABANDONED,
            at=_NOW + timedelta(seconds=1),
            error_code="freshness_exhausted",
        )
        assert await delivery_store.put_breaker(breaker, expected_revision=None) == breaker
        opened = replace(
            breaker,
            mode=ChannelBreakerMode.OPEN,
            revision=1,
            updated_at=_NOW + timedelta(seconds=1),
            reason="failure threshold reached",
        )
        assert await delivery_store.put_breaker(opened, expected_revision=0) == opened
        with pytest.raises(ValueError, match="compare-and-set"):
            await delivery_store.put_breaker(replace(opened, revision=2), expected_revision=0)
        assert await delivery_store.get_breaker(adapter_id) == opened
        assert await delivery_store.delete_expired(now=_NOW + timedelta(minutes=12), limit=200) >= 1
        assert await delivery_store.get(record.delivery_id) is None
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_adapter_breaker WHERE adapter_id = %s",
                (adapter_id,),
            )
            await connection.commit()
        await _cleanup(admin_dsn, binding)
