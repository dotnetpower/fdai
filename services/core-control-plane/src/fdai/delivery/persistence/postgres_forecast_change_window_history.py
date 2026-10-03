"""Read-only ChangeWindow history pages for forecast excluded-window history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.runtime.change_window_history import (
    CHANGE_WINDOW_COVERAGE_PREFIX,
    CHANGE_WINDOW_HISTORY_PREFIX,
)

_MAX_ROWS = 128
_MAX_WINDOW = timedelta(days=31)


@dataclass(frozen=True, slots=True)
class ChangeWindowHistoryRow:
    window_id: str
    scope_ref: str
    window_kind: str
    status: str
    effective_from: datetime
    effective_to: datetime
    source_revision: str
    document_digest: str
    recorded_at: datetime
    revision_ref: str
    supersedes_revision_ref: str | None


@dataclass(frozen=True, slots=True)
class ChangeWindowHistoryCoverage:
    source_revision: str
    document_digest: str
    recorded_at: datetime
    window_count: int
    watermark: str
    revision_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChangeWindowHistoryRead:
    coverage: ChangeWindowHistoryCoverage | None
    rows: tuple[ChangeWindowHistoryRow, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class PostgresForecastChangeWindowHistoryConfig:
    dsn: str
    statement_timeout_ms: int = 3_000
    connect_timeout_s: int = 3

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("forecast change-window history DSN MUST NOT be empty")
        if not 1 <= self.statement_timeout_ms <= 10_000 or not 1 <= self.connect_timeout_s <= 10:
            raise ValueError("forecast change-window history database deadlines are out of bounds")


class PostgresForecastChangeWindowHistoryReader:
    """Read one exact scope's retained ChangeWindow revisions in one read-only snapshot."""

    def __init__(self, *, config: PostgresForecastChangeWindowHistoryConfig) -> None:
        self._config = config

    async def read_history(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> ChangeWindowHistoryRead:
        if not subject_ref or subject_ref != subject_ref.strip() or len(subject_ref) > 512:
            raise ValueError("forecast change-window history requires one exact subject")
        if (
            not _aware(start_at)
            or not _aware(end_at)
            or not _aware(known_at)
            or not start_at <= end_at <= known_at
            or end_at - start_at > _MAX_WINDOW
        ):
            raise ValueError("forecast change-window history query is not causally bounded")
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
            coverage_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key LIKE %s "
                "AND (value ->> 'recorded_at')::timestamptz <= %s "
                "ORDER BY (value ->> 'recorded_at')::timestamptz DESC, key DESC LIMIT 1",
                (CHANGE_WINDOW_COVERAGE_PREFIX + "%", known_at),
            )
            coverage_row = await coverage_cursor.fetchone()
            coverage = _coverage(coverage_row["value"]) if coverage_row is not None else None
            rows: list[ChangeWindowHistoryRow] = []
            truncated = False
            if coverage is not None:
                row_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key LIKE %s "
                    "AND value ->> 'scope_ref' = %s "
                    "AND value ->> 'source_revision' = %s "
                    "AND (value ->> 'recorded_at')::timestamptz <= %s "
                    "AND (value ->> 'effective_to')::timestamptz >= %s "
                    "AND (value ->> 'effective_from')::timestamptz <= %s "
                    "ORDER BY (value ->> 'effective_from')::timestamptz, key LIMIT %s",
                    (
                        CHANGE_WINDOW_HISTORY_PREFIX + "%",
                        subject_ref,
                        coverage.source_revision,
                        known_at,
                        start_at,
                        end_at,
                        _MAX_ROWS + 1,
                    ),
                )
                raw_rows = await row_cursor.fetchall()
                truncated = len(raw_rows) > _MAX_ROWS
                rows = [_row(item["value"]) for item in raw_rows[:_MAX_ROWS]]
        return ChangeWindowHistoryRead(coverage=coverage, rows=tuple(rows), truncated=truncated)


def _coverage(value: object) -> ChangeWindowHistoryCoverage:
    if not isinstance(value, dict):
        raise ValueError("forecast change-window coverage is malformed")
    refs = value.get("revision_refs")
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise ValueError("forecast change-window coverage refs are malformed")
    return ChangeWindowHistoryCoverage(
        source_revision=_text(value, "source_revision"),
        document_digest=_text(value, "document_digest"),
        recorded_at=_timestamp(value, "recorded_at"),
        window_count=int(value.get("window_count", -1)),
        watermark=_text(value, "watermark"),
        revision_refs=tuple(refs),
    )


def _row(value: object) -> ChangeWindowHistoryRow:
    if not isinstance(value, dict):
        raise ValueError("forecast change-window row is malformed")
    supersedes = value.get("supersedes_revision_ref")
    if supersedes is not None and not isinstance(supersedes, str):
        raise ValueError("forecast change-window supersedes reference is malformed")
    return ChangeWindowHistoryRow(
        window_id=_text(value, "window_id"),
        scope_ref=_text(value, "scope_ref"),
        window_kind=_text(value, "window_kind"),
        status=_text(value, "status"),
        effective_from=_timestamp(value, "effective_from"),
        effective_to=_timestamp(value, "effective_to"),
        source_revision=_text(value, "source_revision"),
        document_digest=_text(value, "document_digest"),
        recorded_at=_timestamp(value, "recorded_at"),
        revision_ref=_text(value, "revision_ref"),
        supersedes_revision_ref=supersedes,
    )


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip() or len(item) > 512:
        raise ValueError(f"forecast change-window {key} MUST be bounded text")
    return item


def _timestamp(value: dict[str, object], key: str) -> datetime:
    text = _text(value, key)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"forecast change-window {key} MUST be timezone-aware")
    return parsed


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "ChangeWindowHistoryCoverage",
    "ChangeWindowHistoryRead",
    "ChangeWindowHistoryRow",
    "PostgresForecastChangeWindowHistoryConfig",
    "PostgresForecastChangeWindowHistoryReader",
]
