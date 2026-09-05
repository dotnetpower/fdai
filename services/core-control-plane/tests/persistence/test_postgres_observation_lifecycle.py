"""PostgreSQL correction closure and lifecycle binding tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType
from typing import Any

from fdai.delivery.persistence.postgres_observation_lifecycle import (
    close_observation_corrections,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        if "inventory-ontology:manifest" in query:
            return _Cursor([{"value": {"manifest_digest": DIGEST_A}}])
        if "partition_kind='correction'" in query:
            return _Cursor([{"partition_id": DIGEST_B, "correction_of": DIGEST_A}])
        if "SELECT checkpoint_id" in query:
            return _Cursor([{"checkpoint_id": DIGEST_A}])
        return _Cursor([])

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Connection:
        return self


async def test_projection_closes_pending_correction_with_content_addressed_receipt() -> None:
    connection = _Connection()

    await close_observation_corrections(
        connection,  # type: ignore[arg-type]
        generation="generation-2",
        projection_watermark=10,
        closed_at=NOW,
    )

    inserted = next(
        params
        for query, params in connection.executions
        if "INSERT INTO inventory_observation_correction_receipt" in query
    )
    assert isinstance(inserted, tuple)
    assert str(inserted[0]).startswith("sha256:")
    assert inserted[1] == DIGEST_B
    assert any("SET state='checkpointed'" in query for query, _ in connection.executions)


async def test_concrete_source_purger_calls_only_database_gate() -> None:
    connection = _Connection()
    store = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn="postgresql://unused")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    store._connect = MethodType(connect, store)  # type: ignore[method-assign]
    original_execute = connection.execute

    async def execute(query: str, params: object = None) -> _Cursor:
        if "fdai_purge_observation_partition" in query:
            connection.executions.append((query, params))
            return _Cursor([{"deleted_rows": 1}])
        return await original_execute(query, params)

    connection.execute = execute  # type: ignore[method-assign]

    await store.purge((DIGEST_B,))

    purge_calls = [
        item for item in connection.executions if "fdai_purge_observation_partition" in item[0]
    ]
    assert purge_calls == [
        ("SELECT fdai_purge_observation_partition(%s) AS deleted_rows", (DIGEST_B,))
    ]
