"""Resolve provider identities from the active PostgreSQL inventory generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.delivery.azure.deployment_history import (
    AzureResolvedResourceIdentity,
    AzureResourceIdentityError,
)


@dataclass(frozen=True, slots=True)
class PostgresAzureResourceIdentityResolverConfig:
    """Connection and freshness bounds for server-owned identity resolution."""

    dsn: str
    freshness_budget_seconds: int = 86_400
    statement_timeout_ms: int = 10_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("Postgres Azure identity resolver DSN MUST be non-empty")
        if not 1 <= self.freshness_budget_seconds <= 604_800:
            raise ValueError("identity freshness_budget_seconds MUST be in [1, 604800]")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("identity resolver database timeouts MUST be positive")


class PostgresAzureResourceIdentityResolver:
    """Resolve one neutral id without exposing provider identity to core or Console."""

    def __init__(self, *, config: PostgresAzureResourceIdentityResolverConfig) -> None:
        self._config = config

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime | None = None,
    ) -> AzureResolvedResourceIdentity | None:
        """Return the effective provider ref from one fresh active generation."""

        if not resource_ref.strip():
            raise AzureResourceIdentityError("neutral resource ref MUST be non-empty")
        cutoff = at or datetime.now(tz=UTC)
        if cutoff.tzinfo is None:
            raise AzureResourceIdentityError("provider identity cutoff MUST be timezone-aware")
        try:
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
                if at is None:
                    active_cursor = await connection.execute(
                        "SELECT s.id, s.observation_kind, s.completed_at "
                        "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                        "WHERE a.singleton=TRUE"
                    )
                else:
                    active_cursor = await connection.execute(
                        "SELECT s.id, s.observation_kind, s.completed_at "
                        "FROM inventory_snapshot s "
                        "WHERE s.status IN ('active', 'superseded') "
                        "AND s.observation_kind='observed' AND s.completed_at<=%s "
                        "ORDER BY s.completed_at DESC, s.id DESC LIMIT 1",
                        (cutoff,),
                    )
                active = await active_cursor.fetchone()
                if active is None:
                    return None
                snapshot_id = str(active["id"])
                completed_at = active["completed_at"]
                if (
                    active["observation_kind"] != "observed"
                    or not isinstance(completed_at, datetime)
                    or completed_at.tzinfo is None
                ):
                    return None
                age_seconds = (cutoff - completed_at).total_seconds()
                if age_seconds < 0 or age_seconds > self._config.freshness_budget_seconds:
                    return None
                if at is None:
                    resource_cursor = await connection.execute(
                        "WITH effective AS ("
                        "SELECT d.provider_ref, d.change_kind, d.observed_at, 0 AS priority "
                        "FROM inventory_realtime_resource d WHERE d.resource_id=%s "
                        "UNION ALL "
                        "SELECT r.provider_ref, 'upsert', NULL, 1 "
                        "FROM inventory_snapshot_resource r "
                        "WHERE r.snapshot_id=%s AND r.resource_id=%s AND NOT EXISTS ("
                        "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=%s)) "
                        "SELECT provider_ref, change_kind, observed_at "
                        "FROM effective ORDER BY priority LIMIT 1",
                        (resource_ref, snapshot_id, resource_ref, resource_ref),
                    )
                else:
                    resource_cursor = await connection.execute(
                        "SELECT provider_ref, 'upsert' AS change_kind, NULL AS observed_at "
                        "FROM inventory_snapshot_resource "
                        "WHERE snapshot_id=%s AND resource_id=%s",
                        (snapshot_id, resource_ref),
                    )
                resource = await resource_cursor.fetchone()
        except psycopg.Error as exc:
            raise AzureResourceIdentityError("provider identity store is unavailable") from exc
        if (
            resource is None
            or resource["change_kind"] == "delete"
            or not isinstance(resource["provider_ref"], str)
            or not resource["provider_ref"].strip()
        ):
            return None
        observed_at = resource["observed_at"]
        generation = (
            f"{snapshot_id}:{observed_at.astimezone(UTC).isoformat()}"
            if isinstance(observed_at, datetime) and observed_at.tzinfo is not None
            else snapshot_id
        )
        return AzureResolvedResourceIdentity(
            provider_resource_id=resource["provider_ref"],
            inventory_generation=generation,
        )


__all__ = [
    "PostgresAzureResourceIdentityResolver",
    "PostgresAzureResourceIdentityResolverConfig",
]
