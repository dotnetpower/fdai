"""PostgreSQL inventory progress append and replay tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MethodType
from typing import Any

import pytest
from fdai.delivery.inventory_progress import INVENTORY_PROGRESS_GENESIS_DIGEST
from fdai.delivery.persistence.postgres_inventory_progress import (
    PostgresInventoryProgressStore,
    PostgresInventoryProgressStoreConfig,
)
from fdai_service_contracts import (
    InventoryProgressFractionBasis,
    InventoryProgressRecord,
    InventoryProgressStage,
    InventoryProgressState,
    inventory_progress_record_digest,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)


class _Cursor:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self.rows = list(rows)
        self.executions: list[tuple[str, object]] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        if (
            query.startswith("SELECT sequence")
            or query.startswith("SELECT payload")
            or query.startswith("SELECT fdai_prune_inventory_progress")
        ):
            return _Cursor(self.rows.pop(0))
        return _Cursor()


def _record(
    sequence: int = 1,
    previous: str = INVENTORY_PROGRESS_GENESIS_DIGEST,
    *,
    state: InventoryProgressState = InventoryProgressState.RUNNING,
) -> InventoryProgressRecord:
    stage = (
        InventoryProgressStage.COMPLETE
        if state is InventoryProgressState.COMPLETE
        else InventoryProgressStage.FAILED
        if state is InventoryProgressState.FAILED
        else InventoryProgressStage.COUNT
    )
    complete = state is InventoryProgressState.COMPLETE
    values: dict[str, object] = {
        "run_id": "run.abcdef",
        "attempt_id": "attempt.1",
        "sequence": sequence,
        "previous_digest": previous,
        "stage": stage,
        "state": state,
        "generation_digest": "sha256:" + "1" * 64 if complete else None,
        "scopes_completed": 1 if complete else 0,
        "scopes_total": 1,
        "provider_types_completed": 2 if complete else 0,
        "provider_types_total": 2,
        "resources_observed": 10 if complete else 0,
        "resources_expected": 10,
        "pages_completed": 2 if complete else 0,
        "pages_expected": 2,
        "links_observed": 0,
        "unmapped_objects": 0,
        "coverage_gaps": 0,
        "started_at": NOW,
        "last_progress_at": NOW + timedelta(seconds=1),
        "deadline_at": NOW + timedelta(minutes=5),
        "fraction": 1.0 if complete else 0.05,
        "fraction_basis": (
            InventoryProgressFractionBasis.VERIFIED_CLOSURE
            if complete
            else InventoryProgressFractionBasis.COUNT
        ),
    }
    return InventoryProgressRecord(
        **values,
        record_digest=inventory_progress_record_digest(**values),
    )


def _store(connection: _Connection) -> PostgresInventoryProgressStore:
    store = PostgresInventoryProgressStore(
        config=PostgresInventoryProgressStoreConfig(dsn="postgresql://example")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    store._connect = MethodType(connect, store)  # type: ignore[method-assign]
    return store


async def test_append_locks_chain_and_inserts_exact_payload() -> None:
    connection = _Connection([None, {"deleted_rows": 0}])
    assert await _store(connection).append(_record()) is True

    assert any("pg_advisory_xact_lock" in query for query, _ in connection.executions)
    assert any(
        query.startswith("INSERT INTO inventory_progress_event")
        for query, _ in connection.executions
    )
    assert any(
        query.startswith("SELECT fdai_prune_inventory_progress")
        for query, _ in connection.executions
    )


async def test_append_accepts_only_exact_duplicate() -> None:
    record = _record()
    connection = _Connection(
        [
            {"sequence": 1, "record_digest": record.record_digest},
            {"payload": record.model_dump(mode="json")},
        ]
    )
    assert await _store(connection).append(record) is False

    conflicting = _record()
    retained = {**record.model_dump(mode="json"), "resources_expected": 11}
    with pytest.raises(ValueError, match="retained inventory progress record is invalid"):
        await _store(
            _Connection(
                [
                    {"sequence": 1, "record_digest": record.record_digest},
                    {"payload": retained},
                ]
            )
        ).append(conflicting)


async def test_append_rejects_gap_and_wrong_previous_digest() -> None:
    with pytest.raises(ValueError, match="gap"):
        await _store(_Connection([None])).append(_record(sequence=2))
    with pytest.raises(ValueError, match="previous digest"):
        await _store(_Connection([None])).append(_record(previous="sha256:" + "f" * 64))


async def test_terminal_append_prunes_only_through_database_guard() -> None:
    connection = _Connection([None, {"deleted_rows": 2}])

    assert await _store(connection).append(_record(state=InventoryProgressState.COMPLETE)) is True

    assert any(
        query.startswith("SELECT fdai_prune_inventory_progress") and params == (16,)
        for query, params in connection.executions
    )


def test_inventory_progress_retention_must_be_bounded() -> None:
    with pytest.raises(ValueError, match="terminal retention"):
        PostgresInventoryProgressStoreConfig(
            dsn="postgresql://example",
            terminal_attempt_retention=0,
        )
