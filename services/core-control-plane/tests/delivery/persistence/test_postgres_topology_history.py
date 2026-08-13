"""PostgreSQL topology-history adapter contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType
from typing import Any

from fdai.core.ontology_platform.topology_history import (
    TopologyObjectRevision,
    TopologyRevisionBatch,
)
from fdai.delivery.persistence.postgres_topology_history import (
    PostgresTopologyHistoryStore,
    PostgresTopologyHistoryStoreConfig,
)

EFFECTIVE_AT = datetime(2026, 8, 13, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 13, 1, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


class _Cursor:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        many: list[tuple[str, list[tuple[object, ...]]]] | None = None,
    ) -> None:
        self._rows = rows
        self._many = many

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def executemany(self, query: str, params: list[tuple[object, ...]]) -> None:
        if self._many is None:
            raise AssertionError("executemany requires a connection cursor")
        self._many.append((query, params))


class _Context:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Connection:
    def __init__(self, result_sets: list[list[dict[str, Any]]] | None = None) -> None:
        self.result_sets = list(result_sets or [])
        self.executions: list[tuple[str, object]] = []
        self.many: list[tuple[str, list[tuple[object, ...]]]] = []
        self.transaction_count = 0

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Context:
        self.transaction_count += 1
        return _Context()

    def cursor(self) -> _Cursor:
        return _Cursor([], self.many)

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        rows = (
            self.result_sets.pop(0)
            if query.startswith("SELECT") and "set_config" not in query
            else []
        )
        return _Cursor(rows)


def _batch() -> TopologyRevisionBatch:
    return TopologyRevisionBatch(
        revision_id="revision-1",
        provider_generation_ref="snapshot-1",
        effective_at=EFFECTIVE_AT,
        recorded_at=RECORDED_AT,
        complete_snapshot=True,
        object_revisions=(
            TopologyObjectRevision(
                object_id="vm-1",
                object_type="Resource",
                properties_json='{"id":"vm-1"}',
                effective_at=EFFECTIVE_AT,
                recorded_at=RECORDED_AT,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-1",
            ),
        ),
    )


def _store(connection: _Connection) -> PostgresTopologyHistoryStore:
    store = PostgresTopologyHistoryStore(
        config=PostgresTopologyHistoryStoreConfig(dsn="postgresql://example")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    store._connect = MethodType(connect, store)  # type: ignore[method-assign]
    return store


async def test_append_inserts_batch_and_children_in_one_transaction() -> None:
    connection = _Connection()

    await _store(connection).append(
        _batch(),
        ontology_release_digest=DIGEST,
        source_receipt_digest=DIGEST,
    )

    assert connection.transaction_count == 1
    assert "INSERT INTO topology_revision_batch" in connection.executions[1][0]
    assert len(connection.many) == 1
    assert "INSERT INTO topology_object_revision" in connection.many[0][0]
    assert connection.many[0][1][0][0:3] == ("revision-1", "vm-1", "Resource")
    assert all("ON CONFLICT" not in query for query, _ in connection.executions)


async def test_read_reconstructs_bounded_batches_at_bitemporal_cutoff() -> None:
    connection = _Connection(
        [
            [
                {
                    "revision_id": "revision-1",
                    "provider_generation_ref": "snapshot-1",
                    "effective_at": EFFECTIVE_AT,
                    "recorded_at": RECORDED_AT,
                    "complete_snapshot": True,
                }
            ],
            [
                {
                    "revision_id": "revision-1",
                    "object_id": "vm-1",
                    "object_type": "Resource",
                    "properties": {"id": "vm-1"},
                    "effective_at": EFFECTIVE_AT,
                    "recorded_at": RECORDED_AT,
                    "deleted": False,
                    "evidence_ref": "inventory-generation:snapshot-1",
                }
            ],
            [],
        ]
    )

    batches = await _store(connection).read(as_of=EFFECTIVE_AT, known_at=RECORDED_AT)

    assert batches == (_batch(),)
    batch_query, batch_params = connection.executions[1]
    assert "effective_at <= %s" in batch_query
    assert "recorded_at <= %s" in batch_query
    assert "LIMIT 1001" in batch_query
    assert batch_params == (EFFECTIVE_AT, RECORDED_AT)
