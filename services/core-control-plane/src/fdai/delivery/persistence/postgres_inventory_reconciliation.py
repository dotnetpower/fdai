"""Decide when the inventory job should run a full reconciliation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.inventory_scheduler import (
    CollectionScheduleAction,
    CollectionScheduleDecision,
    CollectionScheduleState,
    ProviderPressure,
    calculate_collection_schedule,
)
from fdai.delivery.inventory_source_policy import SourceCollectionPolicy
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX

_DEFAULT_CHANGE_MIN_INTERVAL_SECONDS: Final[int] = 120
_DEFAULT_FAILURE_BACKOFF_SECONDS: Final[int] = 60
_MAX_CHANGE_MARKERS: Final[int] = 512


@dataclass(frozen=True, slots=True)
class InventoryReconciliationHealthState:
    """Aggregate durable collection facts safe for a health projection."""

    measured_at: datetime
    evidence_age_seconds: float | None
    resource_count: int | None
    relationship_count: int | None
    overlay_resource_count: int
    overlay_relationship_count: int
    cursor_lag_seconds: float | None
    cursor_complete: bool
    coverage_complete: bool
    provider_pressure: ProviderPressure
    newer_failure: bool


class PostgresInventoryReconciliationGate:
    """Decide whether periodic or change demand makes a full scan due."""

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        change_min_interval_seconds: int = _DEFAULT_CHANGE_MIN_INTERVAL_SECONDS,
        source_policy: SourceCollectionPolicy | None = None,
        cursor_scopes: tuple[str, ...] = (),
    ) -> None:
        if change_min_interval_seconds < 1:
            raise ValueError("inventory change_min_interval_seconds MUST be >= 1")
        if any(not scope.strip() for scope in cursor_scopes):
            raise ValueError("inventory cursor scopes MUST be non-empty strings")
        self._config = config
        self._change_min_interval_seconds = change_min_interval_seconds
        self._source_policy = source_policy
        self._cursor_keys = tuple(
            f"inventory_delta_cursor:{scope}" for scope in dict.fromkeys(cursor_scopes)
        )
        self._last_decision: CollectionScheduleDecision | None = None
        self._last_health_state: InventoryReconciliationHealthState | None = None

    @property
    def last_decision(self) -> CollectionScheduleDecision | None:
        """Return the decision produced by the latest completed gate read."""

        return self._last_decision

    @property
    def last_health_state(self) -> InventoryReconciliationHealthState | None:
        """Return aggregate facts used by the latest completed schedule read."""

        return self._last_health_state

    async def __call__(self, interval_seconds: int) -> bool:
        decision = await self.schedule(interval_seconds)
        return decision.due

    async def schedule(self, interval_seconds: int) -> CollectionScheduleDecision:
        """Read durable attempt state and calculate one bounded next action."""

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
                "WITH active AS (SELECT s.id, s.started_at, s.completed_at "
                "FROM inventory_active a "
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
                "AS failure_age_seconds, (SELECT failure_code FROM inventory_snapshot "
                "WHERE status='failed' AND started_at > COALESCE("
                "(SELECT completed_at FROM active), '-infinity'::timestamptz) "
                "ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 1) AS failure_code, "
                "EXISTS (SELECT 1 FROM inventory_snapshot "
                "WHERE status='collecting' AND started_at < NOW() - INTERVAL '30 minutes' "
                "AND started_at > COALESCE((SELECT completed_at FROM active), "
                "'-infinity'::timestamptz)) AS abandoned_attempt, "
                "CASE WHEN EXISTS (SELECT 1 FROM active) THEN "
                "(SELECT count(*) FROM inventory_snapshot_resource r WHERE r.snapshot_id="
                "(SELECT id FROM active)) END AS resource_count, "
                "CASE WHEN EXISTS (SELECT 1 FROM active) THEN "
                "(SELECT count(*) FROM inventory_snapshot_link l WHERE l.snapshot_id="
                "(SELECT id FROM active)) END AS relationship_count, "
                "(SELECT count(*) FROM inventory_realtime_resource) AS overlay_resource_count, "
                "(SELECT count(*) FROM inventory_realtime_link) AS overlay_relationship_count"
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
            if self._cursor_keys:
                cursor_health_cursor = await connection.execute(
                    "SELECT count(*) AS cursor_count, "
                    "MAX(EXTRACT(EPOCH FROM (NOW() - updated_at))) AS cursor_lag_seconds "
                    "FROM state_kv WHERE key=ANY(%s::text[])",
                    (list(self._cursor_keys),),
                )
            else:
                cursor_health_cursor = await connection.execute(
                    "SELECT 0::bigint AS cursor_count, NULL::numeric AS cursor_lag_seconds"
                )
            cursor_health = await cursor_health_cursor.fetchone()
        age = row["age_seconds"]
        failure_age = row["failure_age_seconds"]
        failure_streak = int(row["failure_streak"])
        failure_code = str(row["failure_code"]) if row["failure_code"] else None
        abandoned_attempt = bool(row["abandoned_attempt"])
        provider_pressure = _provider_pressure(
            failure_streak=failure_streak,
            failure_code=failure_code,
            abandoned_attempt=abandoned_attempt,
        )
        change_demand = has_unreconciled_change(
            tuple(marker["value"] for marker in markers),
            active_started_at=row["active_started_at"],
        )
        resource_count = row["resource_count"]
        relationship_count = row["relationship_count"]
        cursor_count = int(cursor_health["cursor_count"] or 0) if cursor_health else 0
        cursor_lag = cursor_health["cursor_lag_seconds"] if cursor_health else None
        cursor_complete = bool(self._cursor_keys) and cursor_count == len(self._cursor_keys)
        self._last_health_state = InventoryReconciliationHealthState(
            measured_at=datetime.now(tz=UTC),
            evidence_age_seconds=float(age) if age is not None else None,
            resource_count=int(resource_count) if resource_count is not None else None,
            relationship_count=(
                int(relationship_count) if relationship_count is not None else None
            ),
            overlay_resource_count=int(row["overlay_resource_count"] or 0),
            overlay_relationship_count=int(row["overlay_relationship_count"] or 0),
            cursor_lag_seconds=float(cursor_lag) if cursor_lag is not None else None,
            cursor_complete=cursor_complete,
            coverage_complete=row["active_started_at"] is not None,
            provider_pressure=provider_pressure,
            newer_failure=failure_streak > 0,
        )
        if self._source_policy is not None:
            self._last_decision = adaptive_reconciliation_decision(
                policy=self._source_policy,
                age_seconds=float(age) if age is not None else None,
                in_progress=bool(row["in_progress"]),
                failure_streak=failure_streak,
                failure_age_seconds=(float(failure_age) if failure_age is not None else None),
                failure_code=failure_code,
                abandoned_attempt=abandoned_attempt,
                change_demand=change_demand,
            )
            return self._last_decision
        due = inventory_reconciliation_due(
            age_seconds=float(age) if age is not None else None,
            in_progress=bool(row["in_progress"]),
            failure_streak=int(row["failure_streak"]),
            failure_age_seconds=float(failure_age) if failure_age is not None else None,
            abandoned_attempt=bool(row["abandoned_attempt"]),
            interval_seconds=interval_seconds,
            change_demand=change_demand,
            change_min_interval_seconds=self._change_min_interval_seconds,
        )
        self._last_decision = CollectionScheduleDecision(
            action=(CollectionScheduleAction.COLLECT if due else CollectionScheduleAction.WAIT),
            due_in_seconds=0.0 if due else float(interval_seconds),
            interval_seconds=float(interval_seconds),
            priority=1,
            concurrency_limit=1,
            freshness_available=age is not None,
            reason_codes=("legacy_due_state",),
        )
        return self._last_decision


def adaptive_reconciliation_decision(
    *,
    policy: SourceCollectionPolicy,
    age_seconds: float | None,
    in_progress: bool,
    failure_streak: int,
    failure_age_seconds: float | None,
    failure_code: str | None,
    abandoned_attempt: bool,
    change_demand: bool,
) -> CollectionScheduleDecision:
    """Map durable reconciliation facts to the pure adaptive controller."""

    if in_progress:
        return CollectionScheduleDecision(
            action=CollectionScheduleAction.WAIT,
            due_in_seconds=float(policy.min_poll_interval_seconds),
            interval_seconds=float(policy.min_poll_interval_seconds),
            priority=policy.priority.base,
            concurrency_limit=1,
            freshness_available=age_seconds is not None,
            reason_codes=("in_progress",),
        )
    pressure = _provider_pressure(
        failure_streak=failure_streak,
        failure_code=failure_code,
        abandoned_attempt=abandoned_attempt,
    )
    return calculate_collection_schedule(
        policy,
        CollectionScheduleState(
            evidence_age_seconds=age_seconds,
            last_attempt_age_seconds=failure_age_seconds,
            change_demand=change_demand,
            failure_streak=failure_streak,
            provider_pressure=pressure,
        ),
    )


def _provider_pressure(
    *,
    failure_streak: int,
    failure_code: str | None,
    abandoned_attempt: bool,
) -> ProviderPressure:
    if abandoned_attempt:
        return ProviderPressure.NO_PROGRESS
    if failure_streak > 0:
        return (
            ProviderPressure.THROTTLED if failure_code == "throttled" else ProviderPressure.TIMEOUT
        )
    return ProviderPressure.HEALTHY


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
    "InventoryReconciliationHealthState",
    "PostgresInventoryReconciliationGate",
    "adaptive_reconciliation_decision",
    "failure_retry_delay_seconds",
    "has_unreconciled_change",
    "inventory_reconciliation_due",
]
