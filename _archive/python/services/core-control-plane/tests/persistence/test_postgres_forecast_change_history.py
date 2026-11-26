from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fdai.delivery.persistence import postgres_forecast_change_history as module
from psycopg import IsolationLevel

NOW = datetime(2026, 9, 20, tzinfo=UTC)
QUERY = module.ForecastChangeHistoryQuery(
    scope_ref="scope-example",
    subject_ref="resource-example",
    start_at=NOW - timedelta(hours=1),
    end_at=NOW,
    known_at=NOW + timedelta(minutes=1),
    page_size=2,
)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.isolation: object = None
        self.read_only = False

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def set_isolation_level(self, value: object) -> None:
        self.isolation = value

    async def set_read_only(self, value: bool) -> None:
        self.read_only = value

    async def execute(self, sql: str, params: tuple[Any, ...]) -> _Cursor:
        self.calls.append((sql, params))
        if "MAX(watermark)" in sql:
            return _Cursor([{"fence": 4}])
        if "FROM inventory_observation_journal" not in sql:
            return _Cursor([])
        rows = [
            {"watermark": value, "effective_at": NOW, "recorded_at": NOW}
            for value in (1, 2, 3, 4, 5)
        ]
        # The fifth row simulates a new concurrent append between pages.
        rows = [row for row in rows if row["watermark"] <= params[6]]
        if "watermark)>(%s, %s, %s)" in sql:
            rows = [row for row in rows if row["watermark"] > params[9]]
        return _Cursor(rows[: params[-1]])


def test_query_and_cursor_reject_cross_scope_or_unbounded_work() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        module.ForecastChangeHistoryQuery("scope", "resource", NOW.replace(tzinfo=None), NOW, NOW)
    with pytest.raises(ValueError, match="31 days"):
        module.ForecastChangeHistoryQuery("scope", "resource", NOW - timedelta(days=32), NOW, NOW)
    with pytest.raises(ValueError, match="page size"):
        module.ForecastChangeHistoryQuery("scope", "resource", NOW, NOW, NOW, page_size=True)
    with pytest.raises(ValueError, match="exact scope"):
        module.ForecastChangeHistoryQuery("", "resource", NOW, NOW, NOW)


async def test_pages_retain_all_rows_with_a_restart_safe_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[_Connection] = []

    async def connect(*args: object, **kwargs: object) -> _Connection:
        del args, kwargs
        connection = _Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    reader = module.PostgresForecastChangeHistoryReader(
        config=module.PostgresForecastChangeHistoryConfig(dsn="postgresql://unused")
    )
    first = await reader.read_page(QUERY)
    assert [row["watermark"] for row in first.rows] == [1, 2]
    assert first.next_cursor is not None
    assert first.fence_watermark == 4
    assert connections[0].isolation is IsolationLevel.REPEATABLE_READ
    assert connections[0].read_only is True
    sql, params = connections[0].calls[-1]
    assert "DISTINCT" not in sql and "source_identity=ANY" in sql
    assert "scope_ref=%s AND subject_ref=%s" in sql
    assert "recorded_at<=%s" in sql
    assert params[0:2] == ("scope-example", "resource-example")
    assert params[6:] == (4, 3)

    second = await reader.read_page(QUERY, cursor=first.next_cursor)
    assert [row["watermark"] for row in second.rows] == [3, 4]
    assert second.next_cursor is None
    assert len(connections[1].calls) == 2  # no new fence lookup
    assert "MAX(watermark)" not in connections[1].calls[-1][0]
    assert connections[1].calls[-1][1][-5:] == (4, NOW, NOW, 2, 3)
    assert [row["watermark"] for row in (await reader.read_page(QUERY)).rows] == [1, 2]


async def test_continuation_refuses_a_different_query_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("invalid cursor accessed the database")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", reject)
    reader = module.PostgresForecastChangeHistoryReader(
        config=module.PostgresForecastChangeHistoryConfig(dsn="postgresql://unused")
    )
    cursor = module.ForecastChangeHistoryCursor(QUERY.identity, 4, NOW, NOW, 2)
    other = module.ForecastChangeHistoryQuery(
        "different-scope", QUERY.subject_ref, QUERY.start_at, QUERY.end_at, QUERY.known_at
    )
    with pytest.raises(ValueError, match="cursor"):
        await reader.read_page(other, cursor=cursor)
    with pytest.raises(ValueError, match="cursor"):
        await reader.read_page(
            QUERY,
            cursor=module.ForecastChangeHistoryCursor(QUERY.identity, 4, NOW, NOW, 5),
        )
