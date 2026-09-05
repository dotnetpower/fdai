"""Focused tests for the bounded lifecycle repository reads the OI-16 campaign adds."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType
from typing import Any

import pytest
from fdai.core.ontology_platform.operational_history_lifecycle import build_correction_receipt
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)
from fdai.delivery.persistence.postgres_operational_history_lifecycle_runner import (
    PostgresOperationalHistoryLifecycleRepository,
    ScopeStorageSample,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
SCOPE = "synthetic/oi16-certification/campaign-a"
DIGEST = "sha256:" + "a" * 64
PARTITION = "sha256:" + "b" * 64


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        self.responses = responses
        self.executions: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        for marker, rows in self.responses.items():
            if marker in query:
                return _Cursor(rows)
        return _Cursor([])

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Connection:
        return self


def _repository(connection: _Connection) -> PostgresOperationalHistoryLifecycleRepository:
    repository = PostgresOperationalHistoryLifecycleRepository(dsn="postgresql://unused")

    async def connect(_self: object) -> _Connection:
        return connection

    repository._connect = MethodType(connect, repository)  # type: ignore[method-assign]
    return repository


def _store(connection: _Connection) -> PostgresOperationalHistoryStore:
    store = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn="postgresql://unused")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    store._connect = MethodType(connect, store)  # type: ignore[method-assign]
    return store


async def test_partition_scope_filter_is_applied_inside_the_bounded_query() -> None:
    connection = _Connection({})
    repository = _repository(connection)

    await repository.list_partitions(limit=64, now=NOW, scope_ref=SCOPE)

    query, params = next(
        item for item in connection.executions if "inventory_observation_partition" in item[0]
    )
    assert "scope_ref = %s" in query
    assert "LIMIT %s" in query
    assert query.index("scope_ref = %s") < query.index("LIMIT %s")
    assert params == (NOW, SCOPE, SCOPE, 64)


async def test_partition_query_without_a_scope_stays_unfiltered() -> None:
    connection = _Connection({})

    await _repository(connection).list_partitions(limit=8, now=NOW)

    _, params = next(
        item for item in connection.executions if "inventory_observation_partition" in item[0]
    )
    assert params == (NOW, None, None, 8)


async def test_scope_storage_measures_tables_indexes_wal_and_change_count() -> None:
    connection = _Connection(
        {
            "pg_table_size": [{"table_bytes": 4096, "index_bytes": 1024}],
            "pg_wal_lsn_diff": [{"wal_bytes": 8192}],
            "COUNT(*) AS partition_count": [
                {"partition_count": 3, "purge_backlog": 1, "change_count": 6}
            ],
        }
    )

    sample = await _repository(connection).measure_scope_storage(scope_ref=SCOPE)

    assert sample == ScopeStorageSample(
        table_bytes=4096,
        index_bytes=1024,
        wal_bytes=8192,
        partition_count=3,
        purge_backlog=1,
        change_count=6,
    )
    assert sample.record()["change_count"] == 6


async def test_scope_storage_refuses_an_empty_scope() -> None:
    with pytest.raises(ValueError, match="MUST NOT be empty"):
        await _repository(_Connection({})).measure_scope_storage(scope_ref="")


async def test_manifest_lookup_by_digest_reads_one_exact_identity() -> None:
    connection = _Connection({})

    assert await _repository(connection).latest_manifest_by_digest(DIGEST) is None
    query, params = connection.executions[-1]
    assert "operational_archive_manifest WHERE manifest_digest=%s" in query
    assert params == (DIGEST,)


async def test_incarnation_listing_is_bounded_and_ordered() -> None:
    connection = _Connection({})

    assert await _store(connection).list_incarnations("resource-a") == ()
    query, params = next(
        item for item in connection.executions if "inventory_resource_incarnation" in item[0]
    )
    assert "ORDER BY opened_at, incarnation_id LIMIT %s" in query
    assert params == ("resource-a", 16)


async def test_incarnation_listing_refuses_an_unbounded_limit() -> None:
    with pytest.raises(ValueError, match="outside its bound"):
        await _store(_Connection({})).list_incarnations("resource-a", limit=1024)


async def test_latest_correction_returns_the_persisted_receipt() -> None:
    receipt = build_correction_receipt(
        correction_partition_id=PARTITION,
        affected_checkpoint_ids=(DIGEST,),
        correction_manifest_digest=DIGEST,
        replay_receipt_digest=DIGEST,
        resulting_graph_digest=DIGEST,
        projection_watermark=11,
        closed_at=NOW,
    )
    record = {
        "receipt_id": receipt.receipt_id,
        "correction_partition_id": receipt.correction_partition_id,
        "affected_checkpoint_ids": list(receipt.affected_checkpoint_ids),
        "correction_manifest_digest": receipt.correction_manifest_digest,
        "replay_receipt_digest": receipt.replay_receipt_digest,
        "resulting_graph_digest": receipt.resulting_graph_digest,
        "projection_watermark": receipt.projection_watermark,
        "closed_at": receipt.closed_at.isoformat(),
        "complete": receipt.complete,
        "digest": receipt.digest,
    }
    connection = _Connection({"inventory_observation_correction_receipt": [{"record": record}]})

    persisted = await _store(connection).latest_correction(PARTITION)

    assert persisted == receipt
    receipt = persisted
    assert receipt.correction_partition_id == PARTITION
    assert receipt.projection_watermark == 11
    assert receipt.complete is True
