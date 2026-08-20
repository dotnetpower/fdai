"""Decide when the inventory job should run a full reconciliation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX

_DEFAULT_CHANGE_MIN_INTERVAL_SECONDS: Final[int] = 120
_DEFAULT_FAILURE_BACKOFF_SECONDS: Final[int] = 60
_MAX_CHANGE_MARKERS: Final[int] = 512


class PostgresInventoryReconciliationGate:
    """Decide whether periodic or change demand makes a full scan due."""

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        change_min_interval_seconds: int = _DEFAULT_CHANGE_MIN_INTERVAL_SECONDS,
    ) -> None:
        if change_min_interval_seconds < 1:
            raise ValueError("inventory change_min_interval_seconds MUST be >= 1")
        self._config = config
        self._change_min_interval_seconds = change_min_interval_seconds

    async def __call__(self, interval_seconds: int) -> bool:
        if interval_seconds < 60:
            raise ValueError("inventory reconciliation interval MUST be >= 60 seconds")
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
                "WITH active AS (SELECT s.started_at, s.completed_at FROM inventory_active a "
                "JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active'), "
                "newer_failures AS (SELECT COALESCE(completed_at, started_at) AS failed_at "
                "FROM inventory_snapshot WHERE status='failed' AND started_at > COALESCE("
                "(SELECT completed_at FROM active), '-infinity'::timestamptz)) "
                "SELECT (SELECT EXTRACT(EPOCH FROM (NOW() - completed_at)) FROM active) "
                "AS age_seconds, (SELECT started_at FROM active) AS active_started_at, "
                "EXISTS (SELECT 1 FROM inventory_snapshot WHERE status='collecting' "
                "AND started_at >= NOW() - INTERVAL '30 minutes') AS in_progress, "
                "(SELECT count(*) FROM newer_failures) AS failure_streak, "
                "(SELECT EXTRACT(EPOCH FROM (NOW() - max(failed_at))) FROM newer_failures) "
                "AS failure_age_seconds, EXISTS (SELECT 1 FROM inventory_snapshot "
                "WHERE status='collecting' AND started_at < NOW() - INTERVAL '30 minutes' "
                "AND started_at > COALESCE((SELECT completed_at FROM active), "
                "'-infinity'::timestamptz)) AS abandoned_attempt"
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("inventory reconciliation gate returned no state")
            marker_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key LIKE %s ORDER BY key LIMIT %s",
                (
                    f"{INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX}%",
                    _MAX_CHANGE_MARKERS + 1,
                ),
            )
            markers = await marker_cursor.fetchall()
        age = row["age_seconds"]
        failure_age = row["failure_age_seconds"]
        return inventory_reconciliation_due(
            age_seconds=float(age) if age is not None else None,
            in_progress=bool(row["in_progress"]),
            failure_streak=int(row["failure_streak"]),
            failure_age_seconds=float(failure_age) if failure_age is not None else None,
            abandoned_attempt=bool(row["abandoned_attempt"]),
            interval_seconds=interval_seconds,
            change_demand=has_unreconciled_change(
                tuple(marker["value"] for marker in markers),
                active_started_at=row["active_started_at"],
            ),
            change_min_interval_seconds=self._change_min_interval_seconds,
        )


def has_unreconciled_change(
    markers: Sequence[Any],
    *,
    active_started_at: datetime | None,
) -> bool:
    """Fail closed when a retained change is newer, malformed, or truncated."""

    if len(markers) > _MAX_CHANGE_MARKERS:
        return True
    for marker in markers:
        recorded_at = _change_marker_recorded_at(marker)
        if recorded_at is None:
            return True
        if active_started_at is None or recorded_at > active_started_at:
            return True
    return False


def _change_marker_recorded_at(value: Any) -> datetime | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("recorded_at", "observed_at"):
        parsed = _marker_timestamp(value.get(key))
        if parsed is not None:
            return parsed
    return None


def _marker_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def failure_retry_delay_seconds(
    *,
    failure_streak: int,
    interval_seconds: int,
    backoff_seconds: int = _DEFAULT_FAILURE_BACKOFF_SECONDS,
) -> float:
    """Return exponential retry delay capped at the routine interval."""

    if failure_streak < 1:
        raise ValueError("failure_streak MUST be >= 1 to earn a retry delay")
    if backoff_seconds < 1:
        raise ValueError("failure backoff_seconds MUST be >= 1")
    exponent = min(failure_streak - 1, 32)
    return float(min(interval_seconds, backoff_seconds * (2**exponent)))


def inventory_reconciliation_due(
    *,
    age_seconds: float | None,
    in_progress: bool,
    abandoned_attempt: bool,
    interval_seconds: int,
    failure_streak: int = 0,
    failure_age_seconds: float | None = None,
    change_demand: bool = False,
    change_min_interval_seconds: int = _DEFAULT_CHANGE_MIN_INTERVAL_SECONDS,
    failure_backoff_seconds: int = _DEFAULT_FAILURE_BACKOFF_SECONDS,
) -> bool:
    """Reduce durable attempt and change state to one deterministic decision."""

    if interval_seconds < 60:
        raise ValueError("inventory reconciliation interval MUST be >= 60 seconds")
    if change_min_interval_seconds < 1:
        raise ValueError("inventory change_min_interval_seconds MUST be >= 1")
    if failure_streak < 0:
        raise ValueError("failure_streak MUST NOT be negative")
    if in_progress:
        return False
    if failure_streak > 0:
        if failure_age_seconds is None:
            return True
        return failure_age_seconds >= failure_retry_delay_seconds(
            failure_streak=failure_streak,
            interval_seconds=interval_seconds,
            backoff_seconds=failure_backoff_seconds,
        )
    if abandoned_attempt or age_seconds is None:
        return True
    if change_demand and age_seconds >= change_min_interval_seconds:
        return True
    return age_seconds >= interval_seconds


__all__ = [
    "PostgresInventoryReconciliationGate",
    "failure_retry_delay_seconds",
    "has_unreconciled_change",
    "inventory_reconciliation_due",
]
