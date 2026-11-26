"""Bounded, read-only journal pages for external-change history witnesses."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.core.ontology_platform.recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
)

_MAX_PAGE = 64
_MAX_WINDOW = timedelta(days=31)
_SOURCE_IDENTITIES = (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class ForecastChangeHistoryQuery:
    """An exact target/window and as-known-at fence, never a coverage assertion."""

    scope_ref: str
    subject_ref: str
    start_at: datetime
    end_at: datetime
    known_at: datetime
    page_size: int = _MAX_PAGE

    def __post_init__(self) -> None:
        if any(
            not value or value != value.strip() or len(value) > 512
            for value in (self.scope_ref, self.subject_ref)
        ):
            raise ValueError("forecast change history requires bounded exact scope and subject")
        if not all(_aware(value) for value in (self.start_at, self.end_at, self.known_at)):
            raise ValueError("forecast change history times MUST be timezone-aware")
        if not self.start_at <= self.end_at <= self.known_at:
            raise ValueError("forecast change history times are not causally ordered")
        if self.end_at - self.start_at > _MAX_WINDOW:
            raise ValueError("forecast change history window exceeds 31 days")
        if isinstance(self.page_size, bool) or not 1 <= self.page_size <= _MAX_PAGE:
            raise ValueError("forecast change history page size MUST be in [1, 64]")

    @property
    def identity(self) -> str:
        body = (
            self.scope_ref,
            self.subject_ref,
            self.start_at.isoformat(),
            self.end_at.isoformat(),
            self.known_at.isoformat(),
        )
        return hashlib.sha256(repr(body).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ForecastChangeHistoryCursor:
    """A restart-safe, query-bound keyset and fixed journal high watermark."""

    query_identity: str
    fence_watermark: int
    effective_at: datetime
    recorded_at: datetime
    watermark: int


@dataclass(frozen=True, slots=True)
class ForecastChangeHistoryPage:
    rows: tuple[dict[str, Any], ...]
    next_cursor: ForecastChangeHistoryCursor | None
    fence_watermark: int


@dataclass(frozen=True, slots=True)
class PostgresForecastChangeHistoryConfig:
    dsn: str
    statement_timeout_ms: int = 5_000
    connect_timeout_s: int = 5

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("forecast change history DSN MUST NOT be empty")
        if not 1 <= self.statement_timeout_ms <= 10_000 or not 1 <= self.connect_timeout_s <= 10:
            raise ValueError("forecast change history database deadlines are out of bounds")


class PostgresForecastChangeHistoryReader:
    """Return every source row in keyset order, not the newest row per subject."""

    def __init__(self, *, config: PostgresForecastChangeHistoryConfig) -> None:
        self._config = config

    async def read_page(
        self,
        query: ForecastChangeHistoryQuery,
        *,
        cursor: ForecastChangeHistoryCursor | None = None,
    ) -> ForecastChangeHistoryPage:
        if cursor is not None and (
            cursor.query_identity != query.identity
            or cursor.fence_watermark < 1
            or not 1 <= cursor.watermark <= cursor.fence_watermark
            or not _aware(cursor.effective_at)
            or not _aware(cursor.recorded_at)
            or not query.start_at <= cursor.effective_at <= query.end_at
            or cursor.recorded_at > query.known_at
        ):
            raise ValueError("forecast change history cursor does not match the bounded query")
        params = (
            query.scope_ref,
            query.subject_ref,
            list(_SOURCE_IDENTITIES),
            query.start_at,
            query.end_at,
            query.known_at,
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
            if cursor is None:
                fence_result = await connection.execute(
                    "SELECT COALESCE(MAX(watermark), 0) AS fence "
                    "FROM inventory_observation_journal WHERE subject_kind='object' "
                    "AND scope_ref=%s AND subject_ref=%s AND source_identity=ANY(%s::text[]) "
                    "AND effective_at>=%s AND effective_at<=%s AND recorded_at<=%s",
                    params,
                )
                fence_row = await fence_result.fetchone()
                if fence_row is None:
                    raise RuntimeError("forecast change history journal fence is unavailable")
                fence = int(fence_row["fence"])
                page_result = await connection.execute(
                    "SELECT watermark, observation_id, content_digest, idempotency_key, "
                    "subject_kind, observation_kind, mutation_kind, scope_ref, subject_ref, "
                    "subject_type, operation, operation_status, source_identity, source_event_id, "
                    "source_revision, effective_at, recorded_at "
                    "FROM inventory_observation_journal WHERE subject_kind='object' "
                    "AND scope_ref=%s AND subject_ref=%s AND source_identity=ANY(%s::text[]) "
                    "AND effective_at>=%s AND effective_at<=%s AND recorded_at<=%s "
                    "AND watermark<=%s "
                    "ORDER BY effective_at, recorded_at, watermark LIMIT %s",
                    (*params, fence, query.page_size + 1),
                )
            else:
                fence = cursor.fence_watermark
                page_result = await connection.execute(
                    "SELECT watermark, observation_id, content_digest, idempotency_key, "
                    "subject_kind, observation_kind, mutation_kind, scope_ref, subject_ref, "
                    "subject_type, operation, operation_status, source_identity, source_event_id, "
                    "source_revision, effective_at, recorded_at "
                    "FROM inventory_observation_journal WHERE subject_kind='object' "
                    "AND scope_ref=%s AND subject_ref=%s AND source_identity=ANY(%s::text[]) "
                    "AND effective_at>=%s AND effective_at<=%s AND recorded_at<=%s "
                    "AND watermark<=%s AND (effective_at, recorded_at, watermark)>(%s, %s, %s) "
                    "ORDER BY effective_at, recorded_at, watermark LIMIT %s",
                    (
                        *params,
                        fence,
                        cursor.effective_at,
                        cursor.recorded_at,
                        cursor.watermark,
                        query.page_size + 1,
                    ),
                )
            rows = await page_result.fetchall()
        retained = tuple(dict(row) for row in rows[: query.page_size])
        next_cursor = None
        if len(rows) > query.page_size:
            last = retained[-1]
            next_cursor = ForecastChangeHistoryCursor(
                query_identity=query.identity,
                fence_watermark=fence,
                effective_at=last["effective_at"],
                recorded_at=last["recorded_at"],
                watermark=int(last["watermark"]),
            )
        return ForecastChangeHistoryPage(retained, next_cursor, fence)


__all__ = [
    "ForecastChangeHistoryCursor",
    "ForecastChangeHistoryPage",
    "ForecastChangeHistoryQuery",
    "PostgresForecastChangeHistoryConfig",
    "PostgresForecastChangeHistoryReader",
]
