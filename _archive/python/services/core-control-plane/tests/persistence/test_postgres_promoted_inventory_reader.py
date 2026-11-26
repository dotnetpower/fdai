"""The promoted inventory reader returns only one complete, reconciled active snapshot."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import psycopg
import pytest
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_promoted_inventory_reader import (
    PostgresPromotedInventoryGenerationReader,
)
from fdai.shared.providers.inventory import (
    PromotedInventoryGenerationLimitError,
    PromotedInventoryGenerationUnavailableError,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration

COMPLETED = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


@asynccontextmanager
async def _isolated_inventory(
    *,
    status: str = "active",
    resource_count: int | None = None,
    resources: tuple[tuple[str, str, dict[str, object]], ...] = (
        ("cache-1", "cache", {"zones": ["1", "2"]}),
        ("cache-2", "cache", {"zones": ["1"]}),
    ),
    active: bool = True,
) -> AsyncIterator[PostgresPromotedInventoryGenerationReader]:
    dsn = os.environ.get("FDAI_ONTOLOGY_TEST_DSN")
    if not dsn:
        pytest.skip("FDAI_ONTOLOGY_TEST_DSN requires a disposable local PostgreSQL")
    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost"}
    schema = "inventory_reader_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
        await admin.execute(f"CREATE SCHEMA {schema}")
        try:
            scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
            async with await psycopg.AsyncConnection.connect(scoped, autocommit=True) as setup:
                await setup.execute(
                    "CREATE TABLE inventory_snapshot (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                    "completed_at TIMESTAMPTZ, resource_count INTEGER);"
                    "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, "
                    "snapshot_id TEXT NOT NULL);"
                    "CREATE TABLE inventory_snapshot_resource (snapshot_id TEXT NOT NULL, "
                    "resource_id TEXT NOT NULL, resource_type TEXT NOT NULL, props JSONB NOT NULL, "
                    "provider_ref TEXT, last_seen TIMESTAMPTZ, "
                    "PRIMARY KEY(snapshot_id, resource_id))"
                )
                await setup.execute(
                    "INSERT INTO inventory_snapshot VALUES ('generation-1', %s, %s, %s)",
                    (
                        status,
                        COMPLETED if status == "active" else None,
                        len(resources) if resource_count is None else resource_count,
                    ),
                )
                if active:
                    await setup.execute(
                        "INSERT INTO inventory_active VALUES (TRUE, 'generation-1')"
                    )
                for resource_id, resource_type, props in resources:
                    await setup.execute(
                        "INSERT INTO inventory_snapshot_resource VALUES "
                        "('generation-1', %s, %s, %s, %s, %s)",
                        (
                            resource_id,
                            resource_type,
                            Jsonb(props),
                            f"/provider/{resource_id}",
                            COMPLETED,
                        ),
                    )
            yield PostgresPromotedInventoryGenerationReader(
                config=PostgresInventorySnapshotStoreConfig(dsn=scoped)
            )
        finally:
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")


async def test_reads_the_complete_active_generation_in_resource_order() -> None:
    async with _isolated_inventory() as reader:
        generation = await reader.load_active_generation(max_resources=10)

    assert generation is not None
    assert generation.generation == "generation-1"
    assert generation.complete is True
    assert generation.recorded_at == COMPLETED
    assert [item.resource_id for item in generation.resources] == ["cache-1", "cache-2"]
    assert generation.resources[0].props == {"zones": ["1", "2"]}
    assert generation.resources[0].provider_ref == "/provider/cache-1"
    async with _isolated_inventory() as reader:
        assert await reader.active_generation_id() == "generation-1"


async def test_no_active_pointer_returns_none() -> None:
    async with _isolated_inventory(active=False) as reader:
        assert await reader.load_active_generation(max_resources=10) is None
        assert await reader.active_generation_id() is None


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"resource_count": 3}, PromotedInventoryGenerationUnavailableError),
        ({"status": "superseded"}, PromotedInventoryGenerationUnavailableError),
        (
            {"resources": (("cache-1", "cache", {"_truncated": True}),)},
            PromotedInventoryGenerationUnavailableError,
        ),
    ],
)
async def test_unusable_generations_fail_closed(
    changes: dict[str, object],
    error: type[Exception],
) -> None:
    async with _isolated_inventory(**changes) as reader:  # type: ignore[arg-type]
        with pytest.raises(error):
            await reader.load_active_generation(max_resources=10)


async def test_generation_over_the_resource_bound_is_rejected_before_reading_rows() -> None:
    async with _isolated_inventory() as reader:
        with pytest.raises(PromotedInventoryGenerationLimitError):
            await reader.load_active_generation(max_resources=1)
        with pytest.raises(ValueError, match="positive"):
            await reader.load_active_generation(max_resources=0)
