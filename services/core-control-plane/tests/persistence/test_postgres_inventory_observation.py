"""PostgreSQL normalized inventory observation journal tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import MethodType
from typing import Any

import pytest
from fdai.delivery.persistence import postgres_inventory_observation as observation_module
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventoryObservationAppendResult,
    PostgresInventoryObservationJournal,
    _append_records,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.rowcount = 0

    async def executemany(self, _query: str, _params: object) -> None:
        return None

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows

    async def fetchone(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, retained: dict[str, object]) -> None:
        self._retained = retained
        self.transactions = 0
        self.executions: list[str] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Connection:
        self.transactions += 1
        return self

    def cursor(self) -> _Cursor:
        return _Cursor([])

    async def execute(self, query: str, _params: object = None) -> _Cursor:
        self.executions.append(query)
        if "WHERE idempotency_key=ANY" in query:
            return _Cursor([self._retained])
        if "SELECT value FROM state_kv" in query:
            return _Cursor([])
        if "SELECT COUNT(*) AS pending" in query:
            return _Cursor([{"pending": 0}])
        return _Cursor([])


def _observation(properties: dict[str, Any]) -> NormalizedInventoryObservation:
    return NormalizedInventoryObservation.create(
        idempotency_key="event:stable",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=InventoryMutationKind.UPSERT,
        subject_ref="resource-1",
        subject_type="compute.vm",
        properties=properties,
        property_mask=tuple(properties),
        properties_complete=True,
        links_complete=False,
        tombstone_confirmed=False,
        source_identity="test.inventory",
        source_event_id="event-1",
        source_revision="revision-1",
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
    )


def _tombstone() -> NormalizedInventoryObservation:
    return NormalizedInventoryObservation.create(
        idempotency_key="event:tombstone",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.TOMBSTONE,
        mutation_kind=InventoryMutationKind.DELETE,
        subject_ref="resource-1",
        subject_type="compute.vm",
        properties={},
        property_mask=(),
        properties_complete=False,
        links_complete=False,
        tombstone_confirmed=False,
        source_identity="test.inventory",
        source_event_id="event-tombstone",
        source_revision="revision-1",
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
    )


async def test_replayed_tombstone_does_not_recreate_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = _tombstone()
    connection = _Connection({})
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )

    async def append_records(
        _connection: object,
        _observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        return InventoryObservationAppendResult(11, 0)

    async def bind(
        _connection: object,
        _observations: Sequence[NormalizedInventoryObservation],
        *,
        allow_oi16_synthetic: bool = False,
    ) -> frozenset[str]:
        del allow_oi16_synthetic
        return frozenset({observation.observation_id})

    monkeypatch.setattr(observation_module, "_append_records", append_records)
    monkeypatch.setattr(observation_module, "bind_observation_lifecycle", bind)

    result = await journal.append_change(
        connection,  # type: ignore[arg-type]
        (observation,),
    )

    assert result == InventoryObservationAppendResult(11, 0)
    assert not any(
        "inventory_observation_pending_tombstone" in query for query in connection.executions
    )


async def test_idempotency_key_rejects_changed_observation_content() -> None:
    retained = _observation({"sku": "old"})
    changed = _observation({"sku": "new"})
    connection = _Connection(
        {
            "watermark": 1,
            "idempotency_key": retained.idempotency_key,
            "subject_kind": retained.subject_kind.value,
            "subject_ref": retained.subject_ref,
            "content_digest": retained.content_digest,
        }
    )

    with pytest.raises(ValueError, match="idempotency key changed content"):
        await _append_records(connection, (changed,))  # type: ignore[arg-type]


async def test_bounded_change_batch_owns_one_transaction_and_delegates() -> None:
    observation = _observation({"sku": "one"})
    connection = _Connection(
        {
            "watermark": 7,
            "idempotency_key": observation.idempotency_key,
            "subject_kind": observation.subject_kind.value,
            "subject_ref": observation.subject_ref,
            "content_digest": observation.content_digest,
        }
    )
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )
    calls: list[Sequence[NormalizedInventoryObservation]] = []

    async def connect(_self: object) -> _Connection:
        return connection

    async def append_change(
        _self: object,
        _connection: object,
        observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        calls.append(observations)
        return InventoryObservationAppendResult(7, 0)

    journal._connect = MethodType(connect, journal)  # type: ignore[method-assign]
    journal.append_change = MethodType(append_change, journal)  # type: ignore[method-assign]

    result = await journal.append_change_batch((observation,))

    assert result == InventoryObservationAppendResult(7, 0)
    assert calls == [(observation,)]
    assert connection.transactions == 1


async def test_bounded_change_batch_refuses_an_unbounded_batch() -> None:
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )

    with pytest.raises(ValueError, match="exceeds its bound"):
        await journal.append_change_batch([_observation({"sku": "one"})] * 1025)
