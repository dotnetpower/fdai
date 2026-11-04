"""Live PostgreSQL checks for Operator-owned inbound channel claims."""

from __future__ import annotations

import hashlib
import os
import runpy
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation.channel_message_ledger import (
    PostgresChannelMessageLedger,
    PostgresChannelMessageLedgerConfig,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

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
    dbname = f"fdai_channel_claim_{uuid4().hex[:12]}"
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


def _key() -> str:
    return hashlib.sha256(uuid4().bytes).hexdigest()


@pytest.mark.integration
async def test_operator_runtime_role_reclaims_and_completes_inbound_claim() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    key = _key()
    store = PostgresChannelMessageLedger(
        config=PostgresChannelMessageLedgerConfig(dsn=operator_dsn, lease_seconds=30)
    )
    try:
        assert await store.claim(key) is True
        assert await store.claim(key) is False

        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "UPDATE conversation_channel_message_claim "
                "SET claimed_at = now() - interval '2 seconds', "
                "lease_expires_at = now() - interval '1 second' "
                "WHERE idempotency_key = %s",
                (key,),
            )
            await connection.commit()

        assert await store.claim(key) is True
        await store.complete(key)
        assert await store.claim(key) is False
        await store.release(key)
        assert await store.claim(key) is False
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (key,),
            )
            await connection.commit()


@pytest.mark.integration
async def test_operator_runtime_role_release_allows_retry_only_while_processing() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    key = _key()
    store = PostgresChannelMessageLedger(
        config=PostgresChannelMessageLedgerConfig(dsn=operator_dsn)
    )
    try:
        assert await store.claim(key) is True
        await store.release(key)
        assert await store.claim(key) is True
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (key,),
            )
            await connection.commit()


async def test_channel_message_ledger_rejects_non_digest_keys() -> None:
    store = PostgresChannelMessageLedger(
        config=PostgresChannelMessageLedgerConfig(dsn="postgresql://example.invalid/db")
    )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        await store.claim("not-a-digest")
