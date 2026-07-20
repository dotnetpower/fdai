from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from fdai.delivery.persistence.postgres_conversation_delivery import (
    PostgresConversationDeliveryStore,
    PostgresConversationDeliveryStoreConfig,
    _breaker_values,
    _delivery_values,
    _row_to_breaker,
    _row_to_delivery,
)
from fdai.delivery.persistence.postgres_principal_binding import (
    PostgresPrincipalConversationBindingStore,
    PostgresPrincipalConversationBindingStoreConfig,
    _row_to_binding,
    _values,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    AdapterBreakerMode,
    AdapterBreakerRecord,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
    PrincipalConversationBinding,
    VerifiedChannelEndpoint,
    new_delivery_record,
)

NOW = datetime(2026, 7, 20, 23, 45, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _binding(*, suffix: str = "example") -> PrincipalConversationBinding:
    endpoint = VerifiedChannelEndpoint(
        principal_id=f"principal-{suffix}",
        scope_ref="scope-example",
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        sender_id=f"vendor-sender-{suffix}",
        thread_id="thread-example",
        verification_ref=f"mapping:{suffix}",
        verified_at=NOW,
    )
    return PrincipalConversationBinding(
        binding_id=f"binding-{suffix}",
        principal_id=endpoint.principal_id,
        scope_ref=endpoint.scope_ref,
        conversation_id="conversation-example",
        endpoint=endpoint,
        created_by=endpoint.principal_id,
        created_at=NOW,
    )


def _delivery(*, suffix: str = "example") -> OutboundDeliveryRecord:
    return new_delivery_record(
        origin_ref=f"turn:{suffix}",
        principal_id=f"principal-{suffix}",
        scope_ref="scope-example",
        conversation_id="conversation-example",
        binding_id=None,
        response=OutboundResponse(
            channel_kind=ConversationChannelKind.SLACK,
            channel_id="channel-example",
            in_reply_to="message-example",
            thread_id="thread-example",
            status="ok",
            text="Persisted response",
            data={"bounded": True},
        ),
        created_at=NOW,
        freshness=timedelta(minutes=15),
        retention=timedelta(days=30),
    )


def test_principal_binding_row_codec_preserves_vendor_and_principal_identities() -> None:
    binding = _binding()
    columns = (
        "binding_id principal_id scope_ref conversation_id channel_kind channel_id sender_id "
        "thread_id verification_ref verified_at created_by created_at resumed_from_binding_id "
        "state revoked_by revoked_at"
    ).split()

    assert _row_to_binding(dict(zip(columns, _values(binding), strict=True))) == binding
    assert binding.endpoint.sender_id != binding.principal_id


def test_delivery_and_breaker_row_codecs_round_trip_complete_state() -> None:
    delivery = _delivery()
    delivery_columns = (
        "delivery_id idempotency_key principal_id scope_ref conversation_id binding_id "
        "channel_kind response response_digest state created_at due_at expires_at retention_until "
        "attempt_count lease_owner lease_expires_at last_error_code duplicate_risk terminal_at"
    ).split()
    breaker = AdapterBreakerRecord(
        adapter_id="slack",
        channel_kind=ConversationChannelKind.SLACK,
        mode=AdapterBreakerMode.OPEN,
        failure_timestamps=(NOW - timedelta(seconds=2), NOW),
        revision=2,
        updated_at=NOW,
        updated_by="system",
        reason="transport_failed",
    )
    breaker_columns = (
        "adapter_id channel_kind mode failure_timestamps revision updated_at updated_by reason"
    ).split()

    assert (
        _row_to_delivery(dict(zip(delivery_columns, _delivery_values(delivery), strict=True)))
        == delivery
    )
    assert (
        _row_to_breaker(dict(zip(breaker_columns, _breaker_values(breaker), strict=True)))
        == breaker
    )


def test_migration_and_store_enforce_claim_and_terminal_contracts() -> None:
    migration = (ROOT / "alembic/versions/20260720_0047_conversation_delivery.py").read_text(
        encoding="utf-8"
    )
    store = (ROOT / "src/fdai/delivery/persistence/postgres_conversation_delivery.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "20260720_0047"' in migration
    assert 'down_revision: str | None = "20260720_0046"' in migration
    assert "WHERE state IN ('pending', 'failed')" in migration
    assert "conversation_outbound_delivery_terminal_guard" in migration
    assert "OLD.state IN ('delivered', 'ambiguous', 'abandoned')" in migration
    assert "FOR UPDATE SKIP LOCKED" in store


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_postgres_binding_and_delivery_claims_are_idempotent() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"]
    suffix = uuid4().hex[:12]
    binding_store = PostgresPrincipalConversationBindingStore(
        config=PostgresPrincipalConversationBindingStoreConfig(dsn=dsn)
    )
    delivery_store = PostgresConversationDeliveryStore(
        config=PostgresConversationDeliveryStoreConfig(dsn=dsn)
    )
    binding = _binding(suffix=suffix)
    delivery = _delivery(suffix=suffix)

    assert await binding_store.create(binding) == binding
    assert await binding_store.create(binding) == binding
    assert await delivery_store.put(delivery) == delivery
    assert await delivery_store.put(delivery) == delivery

    first = await delivery_store.claim(
        delivery_id=delivery.delivery_id,
        now=NOW,
        worker_id="worker-one",
        lease_seconds=30,
    )
    second = await delivery_store.claim(
        delivery_id=delivery.delivery_id,
        now=NOW,
        worker_id="worker-two",
        lease_seconds=30,
    )
    assert first is not None and first.state is OutboundDeliveryState.SENDING
    assert second is None
