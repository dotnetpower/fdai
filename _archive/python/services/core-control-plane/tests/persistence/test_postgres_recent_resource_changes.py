from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.persistence.postgres_recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    PostgresRecentResourceChangeReader,
    PostgresRecentResourceChangeReaderConfig,
    RecentResourceChangePageCursor,
    _change,
    _cursor_coverage_complete,
    _validate_read,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

NOW = datetime(2026, 9, 12, tzinfo=UTC)
LOOPBACK_TEST_DSN = "postgresql://fdai:ci@127.0.0.1:5433/fdai_validation"  # noqa: S105


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
            if "SELECT count(*) AS total" in statement:
                # The count reads the same window as the bounded page.
                assert isinstance(params, tuple) and len(params) == 8
                return _Cursor([{"total": 57}])
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
    # The bound left rows out over complete coverage, so their exact count is kept.
    assert result.total == 57
    assert result.limitation == "result_limit"
    assert connection.isolation_level is module.IsolationLevel.REPEATABLE_READ
    assert connection.read_only is True


@pytest.fixture
def live_database() -> Iterator[str]:
    source = os.environ.get("FDAI_RECENT_RESOURCE_CHANGES_TEST_DSN") or os.environ.get(
        "FDAI_DATABASE_URL", LOOPBACK_TEST_DSN
    )
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parameters = conninfo_to_dict(source)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("recent Resource change database test requires a loopback-only fixture")
    name = "fdai_recent_changes_" + uuid4().hex[:12]
    try:
        admin = psycopg.connect(source, autocommit=True, connect_timeout=2)
    except psycopg.Error:
        pytest.skip("loopback recent Resource change PostgreSQL fixture is unavailable")
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        dsn = make_conninfo(source, dbname=name)
        try:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    """
                    CREATE TABLE inventory_observation_journal (
                        subject_kind TEXT NOT NULL,
                        scope_ref TEXT NOT NULL,
                        subject_ref TEXT NOT NULL,
                        subject_type TEXT NOT NULL,
                        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                        operation TEXT,
                        operation_status TEXT,
                        mutation_kind TEXT NOT NULL,
                        observation_kind TEXT NOT NULL,
                        effective_at TIMESTAMPTZ NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL,
                        source_identity TEXT NOT NULL,
                        source_event_id TEXT NOT NULL,
                        observation_id TEXT NOT NULL,
                        content_digest TEXT NOT NULL
                    );
                    CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            yield dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recent_change_pages_account_every_resource_once_on_postgres(
    live_database: str,
) -> None:
    start_at = NOW - timedelta(days=1)
    known_at = NOW
    scope_ref = "scope-a"
    rows: list[tuple[object, ...]] = []
    for index in range(23):
        subject_ref = f"resource-{index:02d}"
        effective_at = NOW - timedelta(minutes=index // 3)
        rows.append(
            (
                "object",
                scope_ref,
                subject_ref,
                "container-app",
                Jsonb({"name": subject_ref}),
                "Microsoft.Resources/deployments/write",
                "succeeded",
                "upsert",
                "change_hint",
                effective_at,
                NOW - timedelta(seconds=60 - index),
                ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                f"event-{index}",
                f"observation-{index}",
                f"sha256:{index:064x}",
            )
        )
    rows.extend(
        [
            (
                "object",
                scope_ref,
                "resource-05",
                "container-app",
                Jsonb({"name": "older-resource-05"}),
                "Microsoft.Resources/deployments/write",
                "succeeded",
                "upsert",
                "change_hint",
                NOW - timedelta(hours=2),
                NOW - timedelta(seconds=1),
                ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                "event-resource-05-old",
                "observation-resource-05-old",
                "sha256:" + ("5" * 64),
            ),
            (
                "object",
                scope_ref,
                "resource-after-cutoff",
                "container-app",
                Jsonb({"name": "after-cutoff"}),
                "Microsoft.Resources/deployments/write",
                "succeeded",
                "upsert",
                "change_hint",
                NOW,
                NOW + timedelta(seconds=1),
                ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                "event-after-cutoff",
                "observation-after-cutoff",
                "sha256:" + ("9" * 64),
            ),
        ]
    )
    with psycopg.connect(live_database) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO inventory_observation_journal "
                "(subject_kind, scope_ref, subject_ref, subject_type, properties, operation, "
                "operation_status, mutation_kind, observation_kind, effective_at, recorded_at, "
                "source_identity, source_event_id, observation_id, content_digest) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )
        connection.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s)",
            (
                f"arg_resource_change_cursor:{scope_ref}",
                Jsonb(
                    {
                        "complete": True,
                        "last_polled_at": NOW.isoformat(),
                        "pending_event_ids": [],
                    }
                ),
            ),
        )

    reader = PostgresRecentResourceChangeReader(
        config=PostgresRecentResourceChangeReaderConfig(
            dsn=live_database,
            scope_refs=(scope_ref,),
        )
    )
    first = await reader.read_recent_resource_changes(
        start_at=start_at,
        end_at=NOW,
        known_at=known_at,
        limit=7,
    )
    seen = [change.subject_ref for change in first.changes]
    assert first.total == 23
    assert first.complete is False
    assert len(seen) == 7
    cursor = RecentResourceChangePageCursor(
        last_effective_at=first.changes[-1].occurred_at,
        last_subject_ref=first.changes[-1].subject_ref,
    )
    expected_remaining = 23 - len(seen)
    while expected_remaining:
        page = await reader.read_recent_resource_change_page(
            start_at=start_at,
            end_at=NOW,
            known_at=known_at,
            page_size=5,
            cursor=cursor,
        )
        seen.extend(change.subject_ref for change in page.changes)
        expected_remaining = 23 - len(seen)
        assert page.remaining == expected_remaining
        assert page.complete is (expected_remaining == 0)
        if page.cursor is not None:
            cursor = page.cursor

    expected = [
        f"resource-{index:02d}"
        for index in sorted(
            range(23),
            key=lambda item: (NOW - timedelta(minutes=item // 3), f"resource-{item:02d}"),
            reverse=True,
        )
    ]
    expected = sorted(
        (f"resource-{index:02d}" for index in range(23)),
        key=lambda item: (
            -(NOW - timedelta(minutes=int(item.rsplit("-", 1)[1]) // 3)).timestamp(),
            item,
        ),
    )
    assert seen == expected
    assert len(seen) == len(set(seen)) == 23
    assert "resource-after-cutoff" not in seen


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
