"""Live PostgreSQL checks for Operator-owned inbound channel claims."""

from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.conversation.channel_message_ledger import (
    PostgresChannelMessageLedger,
    PostgresChannelMessageLedgerConfig,
)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


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
