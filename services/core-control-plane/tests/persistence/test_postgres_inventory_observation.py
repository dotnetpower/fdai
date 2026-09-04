"""PostgreSQL normalized inventory observation journal tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.delivery.persistence.postgres_inventory_observation import _append_records
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

    def cursor(self) -> _Cursor:
        return _Cursor([])

    async def execute(self, query: str, _params: object = None) -> _Cursor:
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
