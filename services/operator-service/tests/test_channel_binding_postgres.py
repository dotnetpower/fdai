"""Live PostgreSQL checks for Operator-owned principal channel bindings."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelBindingState,
    ChannelKind,
    PrincipalChannelBinding,
    VerifiedChannelEndpoint,
)
from fdai_operator_service.families.conversation.postgres_channel_binding import (
    PostgresChannelBindingConfig,
    PostgresPrincipalChannelBindingStore,
    PrincipalChannelBindingError,
)

_NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _binding(*, suffix: str, binding_id: str | None = None) -> PrincipalChannelBinding:
    principal_id = f"channel-principal-{suffix}"
    scope_ref = f"scope://channel/{suffix}"
    endpoint = VerifiedChannelEndpoint(
        principal_id=principal_id,
        scope_ref=scope_ref,
        channel_kind=ChannelKind.SLACK,
        channel_id=f"channel-{suffix}",
        sender_id=f"sender-{suffix}",
        thread_id=f"thread-{suffix}",
        verification_ref=f"verified-{suffix}",
        verified_at=_NOW,
    )
    return PrincipalChannelBinding(
        binding_id=binding_id or f"binding-{suffix}",
        principal_id=principal_id,
        scope_ref=scope_ref,
        conversation_id=f"conversation-{suffix}",
        endpoint=endpoint,
        created_by="operator-channel-edge",
        created_at=_NOW,
    )


@pytest.mark.integration
async def test_operator_binding_is_idempotent_restart_durable_and_revocable() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    binding = _binding(suffix=suffix)
    store = PostgresPrincipalChannelBindingStore(
        config=PostgresChannelBindingConfig(dsn=operator_dsn)
    )
    try:
        assert await store.create(binding) == binding
        assert await store.create(binding) == binding

        restarted = PostgresPrincipalChannelBindingStore(
            config=PostgresChannelBindingConfig(dsn=operator_dsn)
        )
        assert await restarted.get(binding.binding_id) == binding
        assert await restarted.list_for_principal(principal_id=binding.principal_id) == (binding,)
        revoked = await restarted.revoke(
            binding_id=binding.binding_id,
            expected_state=ChannelBindingState.ACTIVE,
            actor_id="operator-reviewer",
            at=_NOW,
        )
        assert revoked is not None and revoked.state is ChannelBindingState.REVOKED
        assert (
            await restarted.revoke(
                binding_id=binding.binding_id,
                expected_state=ChannelBindingState.ACTIVE,
                actor_id="operator-reviewer",
                at=_NOW,
            )
            is None
        )
        assert await restarted.list_for_principal(principal_id=binding.principal_id) == ()
        assert await restarted.list_for_principal(
            principal_id=binding.principal_id, include_revoked=True
        ) == (revoked,)
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM principal_conversation_binding WHERE binding_id = %s",
                (binding.binding_id,),
            )
            await connection.commit()


@pytest.mark.integration
async def test_operator_binding_rejects_identity_and_active_endpoint_conflicts() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    binding = _binding(suffix=suffix)
    conflicting_id = replace(binding, conversation_id=f"other-{suffix}")
    conflicting_endpoint = replace(binding, binding_id=f"binding-other-{suffix}")
    store = PostgresPrincipalChannelBindingStore(
        config=PostgresChannelBindingConfig(dsn=operator_dsn)
    )
    try:
        await store.create(binding)
        with pytest.raises(PrincipalChannelBindingError, match="different immutable"):
            await store.create(conflicting_id)
        with pytest.raises(PrincipalChannelBindingError, match="active binding"):
            await store.create(conflicting_endpoint)
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM principal_conversation_binding WHERE binding_id = ANY(%s)",
                ([binding.binding_id, conflicting_endpoint.binding_id],),
            )
            await connection.commit()
