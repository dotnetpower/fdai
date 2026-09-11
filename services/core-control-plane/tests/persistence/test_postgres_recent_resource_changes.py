from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.persistence.postgres_recent_resource_changes import (
    _change,
    _cursor_coverage_complete,
    _validate_read,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[dict[str, object]]:
        return self.rows

    async def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, rows: list[dict[str, object]], *, ingested_count: int = 0) -> None:
        self.rows = rows
        self.ingested_count = ingested_count

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def execute(self, statement: str, params: object = None) -> _Cursor:
        del params
        if "AS processed" in statement:
            return _Cursor([{"count": self.ingested_count}])
        return _Cursor(self.rows)


def test_recent_change_read_rejects_invalid_time_or_limit() -> None:
    with pytest.raises(ValueError, match="causally ordered"):
        _validate_read(NOW, NOW - timedelta(seconds=1), NOW, 5)
    with pytest.raises(ValueError, match=r"\[1, 20\]"):
        _validate_read(NOW, NOW, NOW, 21)


def test_recent_change_row_requires_timezone_aware_time() -> None:
    row: dict[str, Any] = {
        "subject_ref": "resource-a",
        "subject_name": "api-prod",
        "subject_type": "container-app",
        "operation": "update",
        "operation_status": "succeeded",
        "mutation_kind": "upsert",
        "observation_kind": "change_hint",
        "effective_at": datetime(2026, 9, 12),
        "source_identity": "activity-log",
        "observation_id": "sha256:" + ("a" * 64),
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        _change(row)


async def test_cursor_coverage_requires_fresh_drained_state() -> None:
    state = {
        "key": "arg_resource_change_cursor:scope-a",
        "value": {
            "complete": True,
            "last_polled_at": NOW.isoformat(),
            "pending_event_ids": [],
        },
    }
    assert await _cursor_coverage_complete(
        _Connection([state]),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
    )


async def test_cursor_coverage_waits_for_every_event_id() -> None:
    state = {
        "key": "arg_resource_change_cursor:scope-a",
        "value": {
            "complete": True,
            "last_polled_at": NOW.isoformat(),
            "pending_event_ids": ["event-1", "event-2"],
        },
    }
    assert not await _cursor_coverage_complete(
        _Connection([state], ingested_count=1),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
    )
    assert await _cursor_coverage_complete(
        _Connection([state], ingested_count=2),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
    )


async def test_ingestion_fence_accepts_terminal_processing_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery.persistence import postgres_recent_resource_changes as module

    connection = _Connection([], ingested_count=2)

    async def connect(*args: object, **kwargs: object) -> _Connection:
        del args, kwargs
        return connection

    monkeypatch.setattr(module.psycopg.AsyncConnection, "connect", connect)
    fence = module.PostgresResourceChangeIngestionFence(
        config=module.PostgresRecentResourceChangeReaderConfig(dsn="postgresql://unused")
    )

    assert await fence.contains(("event-1", "event-2"))
