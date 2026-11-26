"""PostgreSQL topology-history adapter contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType
from typing import Any

from fdai.core.ontology_platform.topology_history import (
    TopologyLinkRevision,
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
        *,
        rowcount: int = 1,
    ) -> None:
        self._rows = rows
        self._many = many
        self.rowcount = rowcount

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
    def __init__(
        self,
        result_sets: list[list[dict[str, Any]]] | None = None,
        *,
        replay: bool = False,
    ) -> None:
        self.result_sets = list(result_sets or [])
        self.executions: list[tuple[str, object]] = []
        self.many: list[tuple[str, list[tuple[object, ...]]]] = []
        self.transaction_count = 0
        self.replay = replay

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
            if query.startswith(("SELECT", "WITH")) and "set_config" not in query
            else []
        )
        return _Cursor(
            rows,
            rowcount=(
                0 if self.replay and query.startswith("INSERT INTO topology_revision_batch") else 1
            ),
        )


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


def _multi_link_batch() -> TopologyRevisionBatch:
    return TopologyRevisionBatch(
        revision_id="revision-multi-link",
        provider_generation_ref="snapshot-multi-link",
        effective_at=EFFECTIVE_AT,
        recorded_at=RECORDED_AT,
        complete_snapshot=True,
        link_revisions=(
            TopologyLinkRevision(
                from_id="resource-b",
                from_type="Resource",
                link_type="attached_to",
                to_id="resource-c",
                to_type="Resource",
                properties_json="{}",
                effective_at=EFFECTIVE_AT,
                recorded_at=RECORDED_AT,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-multi-link",
            ),
            TopologyLinkRevision(
                from_id="resource-a",
                from_type="Resource",
                link_type="routes_to",
                to_id="resource-b",
                to_type="Resource",
                properties_json="{}",
                effective_at=EFFECTIVE_AT,
                recorded_at=RECORDED_AT,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-multi-link",
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
    assert "ON CONFLICT (revision_id) DO NOTHING" in connection.executions[1][0]


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
    assert "WITH latest_complete AS" in batch_query
    assert "AND complete_snapshot" in batch_query
    assert "NOT EXISTS (SELECT 1 FROM latest_complete)" in batch_query
    assert "(recorded_at, revision_id) >=" in batch_query
    assert "effective_at <= %s" in batch_query
    assert "recorded_at <= %s" in batch_query
    assert "LIMIT 1001" in batch_query
    assert batch_params == (EFFECTIVE_AT, RECORDED_AT, EFFECTIVE_AT, RECORDED_AT)


async def test_read_preserves_release_and_source_receipt_bindings() -> None:
    connection = _Connection(
        [
            [
                {
                    "revision_id": "revision-1",
                    "provider_generation_ref": "snapshot-1",
                    "ontology_release_digest": DIGEST,
                    "source_receipt_digest": DIGEST,
                    "effective_at": EFFECTIVE_AT,
                    "recorded_at": RECORDED_AT,
                    "complete_snapshot": True,
                }
            ],
            [],
            [],
        ]
    )

    batches = await _store(connection).read(as_of=EFFECTIVE_AT, known_at=RECORDED_AT)

    assert batches[0].ontology_release_digest == DIGEST
    assert batches[0].source_receipt_digest == DIGEST


async def test_identical_multi_link_replay_uses_publisher_order() -> None:
    batch = _multi_link_batch()
    connection = _Connection(
        [
            [
                {
                    "revision_id": batch.revision_id,
                    "provider_generation_ref": batch.provider_generation_ref,
                    "ontology_release_digest": DIGEST,
                    "source_receipt_digest": DIGEST,
                    "effective_at": EFFECTIVE_AT,
                    "recorded_at": RECORDED_AT,
                    "complete_snapshot": True,
                }
            ],
            [],
            [
                {
                    "revision_id": batch.revision_id,
                    "from_id": item.from_id,
                    "from_type": item.from_type,
                    "link_type": item.link_type,
                    "to_id": item.to_id,
                    "to_type": item.to_type,
                    "properties": {},
                    "effective_at": item.effective_at,
                    "recorded_at": item.recorded_at,
                    "deleted": item.deleted,
                    "evidence_ref": item.evidence_ref,
                }
                for item in batch.link_revisions
            ],
        ],
        replay=True,
    )

    await _store(connection).append(
        batch,
        ontology_release_digest=DIGEST,
        source_receipt_digest=DIGEST,
    )

    assert "ORDER BY link_type, from_id, to_id" in connection.executions[-1][0]
