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
        self.isolation_level: object = None
        self.read_only: bool | None = None

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def set_isolation_level(self, value: object) -> None:
        self.isolation_level = value

    async def set_read_only(self, value: bool) -> None:
        self.read_only = value

    async def execute(self, statement: str, params: object = None) -> _Cursor:
        del params
        if "count(DISTINCT source_event_id)" in statement:
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


async def test_recent_change_reader_reports_result_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery.persistence import postgres_recent_resource_changes as module

    rows = [
        {
            "subject_ref": f"resource-{index}",
            "subject_name": f"resource-{index}",
            "subject_type": "container-app",
            "operation": "update",
            "operation_status": "succeeded",
            "mutation_kind": "upsert",
            "observation_kind": "change_hint",
            "effective_at": NOW - timedelta(seconds=index),
            "source_identity": "activity-log",
            "observation_id": f"observation-{index}",
        }
        for index in range(6)
    ]
    state = {
        "key": "arg_resource_change_cursor:scope-a",
        "value": {
            "complete": True,
            "last_polled_at": NOW.isoformat(),
            "pending_event_ids": [],
        },
    }

    class ReaderConnection(_Connection):
        async def execute(self, statement: str, params: object = None) -> _Cursor:
            if "SELECT * FROM" in statement:
                assert isinstance(params, tuple)
                assert params[-1] == 6
                assert "source_identity=%s" in statement
                assert "azure_event_grid.resource_change" in params
                return _Cursor(rows)
            if "SELECT key, value" in statement:
                return _Cursor([state])
            return _Cursor([])

    connection = ReaderConnection([])

    async def connect(*args: object, **kwargs: object) -> ReaderConnection:
        del args, kwargs
        return connection

    monkeypatch.setattr(module.psycopg.AsyncConnection, "connect", connect)
    reader = module.PostgresRecentResourceChangeReader(
        config=module.PostgresRecentResourceChangeReaderConfig(
            dsn="postgresql://unused",
            scope_refs=("scope-a",),
        )
    )

    result = await reader.read_recent_resource_changes(
        start_at=NOW - timedelta(hours=1),
        end_at=NOW,
        known_at=NOW,
        limit=5,
    )

    assert len(result.changes) == 5
    assert result.complete is False
    assert result.limitation == "result_limit"
    assert connection.isolation_level is module.IsolationLevel.REPEATABLE_READ
    assert connection.read_only is True


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
        window_start_at=NOW - timedelta(hours=1),
        known_at=NOW,
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
        window_start_at=NOW - timedelta(hours=1),
        known_at=NOW,
    )
    assert await _cursor_coverage_complete(
        _Connection([state], ingested_count=2),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
        window_start_at=NOW - timedelta(hours=1),
        known_at=NOW,
    )


async def test_cursor_coverage_rejects_poll_after_known_at() -> None:
    state = {
        "key": "arg_resource_change_cursor:scope-a",
        "value": {
            "complete": True,
            "last_polled_at": (NOW + timedelta(seconds=1)).isoformat(),
            "pending_event_ids": [],
        },
    }

    assert not await _cursor_coverage_complete(
        _Connection([state]),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
        window_start_at=NOW - timedelta(hours=1),
        known_at=NOW,
    )


async def test_cursor_coverage_discloses_intersecting_hydration_gap() -> None:
    state = {
        "key": "arg_resource_change_cursor:scope-a",
        "value": {
            "complete": True,
            "coverage_gap_at": (NOW - timedelta(minutes=30)).isoformat(),
            "last_polled_at": NOW.isoformat(),
            "pending_event_ids": [],
        },
    }

    assert not await _cursor_coverage_complete(
        _Connection([state]),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
        window_start_at=NOW - timedelta(hours=1),
        known_at=NOW,
    )
    assert await _cursor_coverage_complete(
        _Connection([state]),  # type: ignore[arg-type]
        scope_refs=("scope-a",),
        required_at=NOW - timedelta(minutes=1),
        window_start_at=NOW - timedelta(minutes=10),
        known_at=NOW,
    )


async def test_ingestion_fence_accepts_journaled_events(
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
