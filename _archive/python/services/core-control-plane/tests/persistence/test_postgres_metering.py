"""PostgreSQL metering retention tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.usage import TokenUsage
from fdai.delivery.persistence.postgres_metering import (
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _isolated_store(*, max_records: int) -> AsyncIterator[PostgresMeteringStore]:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL requires a disposable local PostgreSQL")
    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost"}
    schema = "metering_retention_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
        await admin.execute(f"CREATE SCHEMA {schema}")
        try:
            scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
            async with await psycopg.AsyncConnection.connect(scoped) as connection:
                await connection.execute(
                    "CREATE TABLE llm_invocation ("
                    "invocation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                    "occurred_at TIMESTAMPTZ NOT NULL, correlation_id TEXT NOT NULL, "
                    "capability_id TEXT NOT NULL, model_key TEXT NOT NULL, tier TEXT NOT NULL, "
                    "mode TEXT NOT NULL, usage_scope TEXT NOT NULL, prompt_tokens BIGINT NOT NULL, "
                    "completion_tokens BIGINT NOT NULL, cost NUMERIC, currency TEXT, "
                    "UNIQUE (occurred_at, correlation_id, capability_id, model_key, tier, mode, "
                    "usage_scope, prompt_tokens, completion_tokens))"
                )
            yield PostgresMeteringStore(
                config=PostgresMeteringStoreConfig(dsn=scoped, max_records=max_records)
            )
        finally:
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")


def _invocation(index: int) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC) + timedelta(seconds=index),
        correlation_id=f"event-{index}",
        capability_id="t1.judge",
        model_key="model-small",
        tier="T1",
        mode=InvocationMode.SHADOW,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
    )


async def test_postgres_metering_evicts_oldest_records() -> None:
    async with _isolated_store(max_records=2) as store:
        for index in range(4):
            await store.record(_invocation(index))

        retained = await store.invocations()

    assert [item.correlation_id for item in retained] == ["event-2", "event-3"]


def test_postgres_metering_rejects_nonpositive_retention() -> None:
    with pytest.raises(ValueError, match="max_records"):
        PostgresMeteringStoreConfig(dsn="postgresql://example/fdai", max_records=0)
