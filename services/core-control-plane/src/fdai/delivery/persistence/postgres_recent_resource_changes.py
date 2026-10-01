"""PostgreSQL reader and exact ingestion fence for Resource changes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.core.ontology_platform.recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    RecentResourceChange,
    RecentResourceChangePageCursor,
    RecentResourceChangePageRead,
    RecentResourceChangeRead,
)


@dataclass(frozen=True, slots=True)
class PostgresRecentResourceChangeReaderConfig:
    dsn: str
    scope_refs: tuple[str, ...] = ()
    cursor_freshness_seconds: int = 180
    statement_timeout_ms: int = 10_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("recent Resource change reader DSN MUST NOT be empty")
        if self.scope_refs != tuple(sorted(set(self.scope_refs))):
            raise ValueError("recent Resource change reader scopes MUST be unique and ordered")
        if any(not scope.strip() or len(scope) > 512 for scope in self.scope_refs):
            raise ValueError("recent Resource change reader scopes MUST be bounded")
        if (
            min(
                self.cursor_freshness_seconds,
                self.statement_timeout_ms,
                self.connect_timeout_s,
            )
            < 1
        ):
            raise ValueError("recent Resource change reader timeouts MUST be positive")


# The newest observed change of each Resource in one window, as recorded by one cutoff.
_NEWEST_CHANGE_SQL = (
    "SELECT DISTINCT ON (subject_ref) "
    "subject_ref, properties->>'name' AS subject_name, subject_type, "
    "operation, operation_status, mutation_kind, observation_kind, "
    "effective_at, source_identity, observation_id "
    "FROM inventory_observation_journal "
    "WHERE subject_kind='object' "
    "AND ((source_identity=%s "
    "AND observation_kind=ANY(%s::text[])) "
    "OR (source_identity=%s "
    "AND operation IS NOT NULL AND observation_kind=ANY(%s::text[]))) "
    "AND scope_ref=ANY(%s::text[]) "
    "AND effective_at>=%s AND effective_at<=%s AND recorded_at<=%s "
    "ORDER BY subject_ref, effective_at DESC, recorded_at DESC, "
    "source_event_id DESC, content_digest DESC"
)
_ORDERING_SQL = "ORDER BY effective_at DESC, subject_ref ASC"
_PAGE_SEEK_SQL = "WHERE effective_at < %s OR (effective_at = %s AND subject_ref > %s) "
_FIRST_PAGE_SQL = (
    "SELECT * FROM (" + _NEWEST_CHANGE_SQL + ") AS newest " + _ORDERING_SQL + " LIMIT %s"  # noqa: S608 - module constants
)
_CONTINUATION_PAGE_SQL = (
    "SELECT * FROM ("  # noqa: S608 - module constants
    + _NEWEST_CHANGE_SQL
    + ") AS newest "
    + _PAGE_SEEK_SQL
    + _ORDERING_SQL
    + " LIMIT %s"
)
_CONTINUATION_REMAINING_SQL = (
    "SELECT count(*) AS remaining FROM ("  # noqa: S608 - module constants
    + _NEWEST_CHANGE_SQL
    + ") AS newest "
    + _PAGE_SEEK_SQL
)


class PostgresRecentResourceChangeReader:
    def __init__(self, *, config: PostgresRecentResourceChangeReaderConfig) -> None:
        self._config = config

    def query_version_digest(self) -> str:
        return _query_version_digest(self._config.scope_refs)

    async def read_recent_resource_changes(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> RecentResourceChangeRead:
        _validate_read(start_at, end_at, known_at, limit)
        if not self._config.scope_refs:
            return RecentResourceChangeRead((), False, "resource_change_coverage_unverified")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            window = (
                ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                ["full", "tombstone"],
                ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                ["partial", "change_hint", "tombstone"],
                list(self._config.scope_refs),
                start_at,
                end_at,
                known_at,
            )
            cursor = await connection.execute(
                _FIRST_PAGE_SQL,  # noqa: S608 - module constant
                (*window, limit + 1),
            )
            rows = await cursor.fetchall()
            source_complete = await _cursor_coverage_complete(
                connection,
                scope_refs=self._config.scope_refs,
                required_at=end_at - timedelta(seconds=self._config.cursor_freshness_seconds),
                window_start_at=start_at,
                known_at=known_at,
            )
            truncated = len(rows) > limit
            total: int | None = None
            if truncated and source_complete:
                # The same snapshot counts every changed Resource the bound left out, so the
                # answer states exactly how many rows it does not list.
                counted = await connection.execute(
                    "SELECT count(*) AS total FROM (" + _NEWEST_CHANGE_SQL + ") AS newest",  # noqa: S608 - module constant
                    window,
                )
                row = await counted.fetchone()
                total = int(row["total"]) if row is not None else None
        return RecentResourceChangeRead(
            tuple(_change(row) for row in rows[:limit]),
            source_complete and not truncated,
            (
                "result_limit"
                if truncated
                else None
                if source_complete
                else "resource_change_coverage_unverified"
            ),
            total=total if total is not None and total > limit else None,
        )

    async def read_recent_resource_change_page(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        page_size: int,
        cursor: RecentResourceChangePageCursor,
    ) -> RecentResourceChangePageRead:
        _validate_page_read(start_at, end_at, known_at, page_size, cursor)
        if not self._config.scope_refs:
            return RecentResourceChangePageRead(
                (),
                False,
                0,
                None,
                "resource_change_coverage_unverified",
            )
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            window = (
                ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                ["full", "tombstone"],
                ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                ["partial", "change_hint", "tombstone"],
                list(self._config.scope_refs),
                start_at,
                end_at,
                known_at,
            )
            seek = (cursor.last_effective_at, cursor.last_effective_at, cursor.last_subject_ref)
            page_result = await connection.execute(
                _CONTINUATION_PAGE_SQL,  # noqa: S608 - module constant
                (*window, *seek, page_size + 1),
            )
            rows = await page_result.fetchall()
            source_complete = await _cursor_coverage_complete(
                connection,
                scope_refs=self._config.scope_refs,
                required_at=end_at - timedelta(seconds=self._config.cursor_freshness_seconds),
                window_start_at=start_at,
                known_at=known_at,
            )
            retained = rows[:page_size]
            next_cursor = (
                RecentResourceChangePageCursor(
                    last_effective_at=retained[-1]["effective_at"].astimezone(UTC),
                    last_subject_ref=str(retained[-1]["subject_ref"]),
                )
                if retained
                else None
            )
            remaining = 0
            if next_cursor is not None:
                remaining_result = await connection.execute(
                    _CONTINUATION_REMAINING_SQL,  # noqa: S608 - module constant
                    (
                        *window,
                        next_cursor.last_effective_at,
                        next_cursor.last_effective_at,
                        next_cursor.last_subject_ref,
                    ),
                )
                remaining_row = await remaining_result.fetchone()
                remaining = int(remaining_row["remaining"]) if remaining_row is not None else 0
        truncated = remaining > 0
        return RecentResourceChangePageRead(
            tuple(_change(row) for row in retained),
            source_complete and not truncated,
            remaining if source_complete else 0,
            next_cursor if source_complete and truncated else None,
            (
                "result_limit"
                if truncated
                else None
                if source_complete
                else "resource_change_coverage_unverified"
            ),
        )


class PostgresResourceChangeIngestionFence:
    def __init__(self, *, config: PostgresRecentResourceChangeReaderConfig) -> None:
        self._config = config

    async def contains(self, event_ids: tuple[str, ...]) -> bool:
        if not event_ids or event_ids != tuple(sorted(set(event_ids))) or len(event_ids) > 1_000:
            raise ValueError("resource change ingestion fence ids MUST be unique and ordered")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                _PROCESSED_EVENT_COUNT_SQL,
                (ARG_RESOURCE_CHANGE_SOURCE_IDENTITY, list(event_ids)),
            )
            row = await cursor.fetchone()
        return row is not None and int(row["count"]) == len(event_ids)


def _change(row: dict[str, Any]) -> RecentResourceChange:
    occurred_at = row["effective_at"]
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise ValueError("recent Resource change timestamp MUST be timezone-aware")
    return RecentResourceChange(
        subject_ref=str(row["subject_ref"]),
        subject_name=(
            str(row["subject_name"])
            if row["subject_name"] is not None and str(row["subject_name"]).strip()
            else None
        ),
        subject_type=str(row["subject_type"]),
        operation=str(row["operation"]) if row["operation"] is not None else None,
        operation_status=(
            str(row["operation_status"]) if row["operation_status"] is not None else None
        ),
        mutation_kind=str(row["mutation_kind"]),
        observation_kind=str(row["observation_kind"]),
        occurred_at=occurred_at.astimezone(UTC),
        source_identity=str(row["source_identity"]),
        evidence_ref=f"inventory-observation:{row['observation_id']}",
    )


async def _cursor_coverage_complete(
    connection: psycopg.AsyncConnection[Any],
    *,
    scope_refs: tuple[str, ...],
    required_at: datetime,
    window_start_at: datetime,
    known_at: datetime,
) -> bool:
    if not scope_refs:
        return False
    cursor = await connection.execute(
        "SELECT key, value FROM state_kv WHERE key=ANY(%s::text[]) ORDER BY key",
        ([f"arg_resource_change_cursor:{scope}" for scope in scope_refs],),
    )
    rows = await cursor.fetchall()
    if len(rows) != len(scope_refs):
        return False
    for scope_ref, row in zip(scope_refs, rows, strict=True):
        if row.get("key") != f"arg_resource_change_cursor:{scope_ref}":
            return False
        value = row["value"]
        if not isinstance(value, dict) or value.get("complete") is not True:
            return False
        coverage_gap_at = value.get("coverage_gap_at")
        if coverage_gap_at is not None:
            try:
                gap_at = datetime.fromisoformat(str(coverage_gap_at).replace("Z", "+00:00"))
            except ValueError:
                return False
            if gap_at.tzinfo is None or gap_at.astimezone(UTC) >= window_start_at.astimezone(UTC):
                return False
        raw = value.get("last_polled_at")
        if not isinstance(raw, str):
            return False
        try:
            polled_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if (
            polled_at.tzinfo is None
            or polled_at.astimezone(UTC) < required_at.astimezone(UTC)
            or polled_at.astimezone(UTC) > known_at.astimezone(UTC)
        ):
            return False
        pending = value.get("pending_event_ids")
        if (
            not isinstance(pending, list)
            or len(pending) > 1_000
            or any(not isinstance(item, str) or not item or len(item) > 128 for item in pending)
            or len(set(pending)) != len(pending)
        ):
            return False
        if not pending:
            continue
        ingested = await connection.execute(
            _PROCESSED_EVENT_COUNT_AT_SQL,
            (ARG_RESOURCE_CHANGE_SOURCE_IDENTITY, pending, known_at),
        )
        ingested_row = await ingested.fetchone()
        if (
            ingested_row is None
            or not isinstance(ingested_row["count"], int)
            or ingested_row["count"] != len(pending)
        ):
            return False
    return True


_PROCESSED_EVENT_COUNT_SQL = (
    "SELECT count(DISTINCT source_event_id) AS count "
    "FROM inventory_observation_journal "
    "WHERE source_identity=%s "
    "AND source_event_id=ANY(%s::text[])"
)
_PROCESSED_EVENT_COUNT_AT_SQL = (
    "SELECT count(DISTINCT source_event_id) AS count "
    "FROM inventory_observation_journal "
    "WHERE source_identity=%s "
    "AND source_event_id=ANY(%s::text[]) AND recorded_at<=%s"
)


def _validate_read(
    start_at: datetime,
    end_at: datetime,
    known_at: datetime,
    limit: int,
) -> None:
    if any(
        value.tzinfo is None or value.utcoffset() is None for value in (start_at, end_at, known_at)
    ):
        raise ValueError("recent Resource change times MUST be timezone-aware")
    if not start_at <= end_at <= known_at:
        raise ValueError("recent Resource change times are not causally ordered")
    if not 1 <= limit <= 20:
        raise ValueError("recent Resource change limit MUST be in [1, 20]")


def _validate_page_read(
    start_at: datetime,
    end_at: datetime,
    known_at: datetime,
    page_size: int,
    cursor: RecentResourceChangePageCursor,
) -> None:
    _validate_read(start_at, end_at, known_at, page_size)
    if (
        cursor.last_effective_at.tzinfo is None
        or cursor.last_effective_at.utcoffset() is None
        or not start_at <= cursor.last_effective_at <= end_at
        or not cursor.last_subject_ref
        or len(cursor.last_subject_ref) > 512
    ):
        raise ValueError("recent Resource change continuation cursor is invalid")


def _query_version_digest(scope_refs: tuple[str, ...]) -> str:
    payload = {
        "newest_sql": _NEWEST_CHANGE_SQL,
        "ordering_sql": _ORDERING_SQL,
        "page_seek_sql": _PAGE_SEEK_SQL,
        "source_filters": {
            "arg": {
                "source_identity": ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                "observation_kind": ["full", "tombstone"],
            },
            "activity_log": {
                "source_identity": ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                "observation_kind": ["partial", "change_hint", "tombstone"],
                "operation_required": True,
            },
            "scope_refs": list(scope_refs),
        },
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


__all__ = [
    "PostgresRecentResourceChangeReader",
    "PostgresRecentResourceChangeReaderConfig",
    "PostgresResourceChangeIngestionFence",
]
