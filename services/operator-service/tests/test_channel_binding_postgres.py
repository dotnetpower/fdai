"""Live PostgreSQL checks for Operator-owned principal channel bindings."""

from __future__ import annotations

import os
import runpy
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
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
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[3]
_BASE_MIGRATION = _ROOT / "alembic/versions/20260720_0047_conversation_delivery.py"
_EDGE_MIGRATION = (
    _ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260819_operator_a3_channel_delivery.py"
)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module", autouse=True)
def _ensure_channel_postgres_dsns() -> Iterator[None]:
    if os.environ.get("FDAI_ADMIN_DATABASE_URL", "").strip():
        yield
        return
    raw_base = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw_base:
        yield
        return
    base_dsn = raw_base.replace("postgresql+psycopg://", "postgresql://", 1)
    params = conninfo_to_dict(base_dsn)
    if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("channel PostgreSQL integration tests require a loopback fixture")
    dbname = f"fdai_channel_bind_{uuid4().hex[:12]}"
    statements: list[str] = []
    for path in (_BASE_MIGRATION, _EDGE_MIGRATION):
        module = runpy.run_path(str(path))
        with patch("alembic.op.execute", side_effect=statements.append):
            module["upgrade"]()
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(
            """DO $roles$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_operator') THEN
                CREATE ROLE fdai_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            END; $roles$"""
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    disposable_admin = make_conninfo(base_dsn, dbname=dbname)
    disposable_operator = make_conninfo(disposable_admin, options="-c role=fdai_operator")
    prev_admin = os.environ.get("FDAI_ADMIN_DATABASE_URL")
    prev_db = os.environ.get("FDAI_DATABASE_URL")
    try:
        with psycopg.connect(disposable_admin) as conn:
            conn.execute("GRANT USAGE ON SCHEMA public TO fdai_operator")
            for statement in statements:
                conn.execute(statement)
        os.environ["FDAI_ADMIN_DATABASE_URL"] = disposable_admin
        os.environ["FDAI_DATABASE_URL"] = disposable_operator
        yield
    finally:
        if prev_admin is None:
            os.environ.pop("FDAI_ADMIN_DATABASE_URL", None)
        else:
            os.environ["FDAI_ADMIN_DATABASE_URL"] = prev_admin
        if prev_db is None:
            os.environ.pop("FDAI_DATABASE_URL", None)
        else:
            os.environ["FDAI_DATABASE_URL"] = prev_db
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))


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
