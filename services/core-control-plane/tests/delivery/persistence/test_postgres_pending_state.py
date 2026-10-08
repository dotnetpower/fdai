"""Pending same-type descriptor reads: row shaping, overflow, bounds, and failure mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fdai.core.ontology_platform.pending_state_coverage import (
    PendingStateDescriptorUnavailableError,
)
from fdai.delivery.persistence.postgres_pending_state import (
    PostgresPendingStateDescriptorReader,
    descriptor_from_rows,
)

NOW = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)


def _row(index: int, **changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_id": "generation-a",
        "observation_id": f"observation-{index}",
        "subject_ref": f"scope-a/resource-group/rg/vm-{index}",
        "subject_type": "compute.vm",
        "provider_ref": f"/subscriptions/example/virtualMachines/vm-{index}",
        "mutation_kind": "upsert",
        "tombstone_confirmed": False,
        "effective_at": NOW,
    }
    row.update(changes)
    return row


def test_no_active_generation_yields_an_empty_descriptor() -> None:
    descriptor = descriptor_from_rows([], limit=10)
    assert descriptor.generation is None
    assert descriptor.observations == ()
    assert descriptor.overflow is False


def test_a_generation_without_pending_rows_has_no_observations() -> None:
    row = {key: None for key in _row(0)} | {"snapshot_id": "generation-a"}
    descriptor = descriptor_from_rows([row], limit=10)
    assert descriptor.generation == "generation-a"
    assert descriptor.observations == ()


def test_rows_become_observations_and_one_extra_row_marks_overflow() -> None:
    rows = [_row(1), _row(2, provider_ref=None, tombstone_confirmed=True), _row(3)]
    bounded = descriptor_from_rows(rows[:2], limit=2)
    assert bounded.overflow is False
    assert [item.observation_id for item in bounded.observations] == [
        "observation-1",
        "observation-2",
    ]
    assert bounded.observations[1].provider_ref is None
    assert bounded.observations[1].tombstone is True
    overflow = descriptor_from_rows(rows, limit=2)
    assert overflow.overflow is True
    assert len(overflow.observations) == 2


@pytest.mark.parametrize(("types", "limit"), [((), 5), (("compute.vm",), 0), (("x",), 11)])
async def test_the_reader_rejects_unbounded_requests(types: tuple[str, ...], limit: int) -> None:
    reader = PostgresPendingStateDescriptorReader(dsn="postgresql://localhost/example")
    with pytest.raises(ValueError, match="limit"):
        await reader.pending_state_descriptor(subject_types=types, limit=limit)


def test_the_reader_requires_a_dsn() -> None:
    with pytest.raises(ValueError, match="DSN"):
        PostgresPendingStateDescriptorReader(dsn=" ")


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.statements: list[tuple[str, tuple[Any, ...] | None]] = []
        self._rows = rows

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.statements.append((sql, params))
        return _Cursor(self._rows)


async def test_the_reader_uses_one_repeatable_read_snapshot_with_the_typed_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([_row(1)])

    async def connect(dsn: str, **_: Any) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    reader = PostgresPendingStateDescriptorReader(dsn="postgresql://localhost/example")

    descriptor = await reader.pending_state_descriptor(subject_types=("compute.vm",), limit=3)

    assert descriptor.generation == "generation-a"
    assert [statement for statement, _ in connection.statements][0] == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    sql, params = connection.statements[-1]
    assert "journal.subject_type=ANY(%s::text[])" in sql
    assert "ORDER BY journal.watermark LIMIT %s" in sql
    assert params is not None
    assert params[1:] == (["compute.vm"], 4)


async def test_a_database_failure_is_reported_as_an_unavailable_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connect(dsn: str, **_: Any) -> _Connection:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    reader = PostgresPendingStateDescriptorReader(dsn="postgresql://localhost/example")
    with pytest.raises(PendingStateDescriptorUnavailableError):
        await reader.pending_state_descriptor(subject_types=("compute.vm",), limit=3)
