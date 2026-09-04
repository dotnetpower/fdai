"""Resolve exact Azure WARA scopes from promoted inventory and ontology links."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.delivery.azure.arg_projection import arm_id_to_type

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")


class WaraScopeUnavailableError(RuntimeError):
    """A workload cannot be bound to one complete current Azure scope."""


@dataclass(frozen=True, slots=True)
class PostgresWaraScopeSourceConfig:
    """Bound the promoted-inventory scope read."""

    dsn: str
    freshness_budget_seconds: int = 86_400
    maximum_resources: int = 1_000
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("PostgresWaraScopeSourceConfig.dsn MUST be non-empty")
        if not 1 <= self.freshness_budget_seconds <= 604_800:
            raise ValueError("freshness_budget_seconds MUST be in [1, 604800]")
        if not 1 <= self.maximum_resources <= 1_000:
            raise ValueError("maximum_resources MUST be in [1, 1000]")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("database timeouts MUST be positive")


@dataclass(frozen=True, slots=True)
class WaraResolvedResource:
    """One ontology-linked resource with its exact Azure identity."""

    neutral_resource_id: str
    provider_resource_id: str
    provider_resource_type: str


@dataclass(frozen=True, slots=True)
class WaraResolvedScope:
    """One complete workload scope pinned to inventory and ontology generations."""

    workload_id: str
    ontology_release: str
    inventory_generation: str
    resources: tuple[WaraResolvedResource, ...]


class PostgresWaraScopeSource:
    """Read a complete current workload scope without exposing arbitrary SQL."""

    def __init__(self, *, config: PostgresWaraScopeSourceConfig) -> None:
        self._config = config

    async def resolve(
        self,
        workload_id: str,
        *,
        now: datetime | None = None,
    ) -> WaraResolvedScope:
        """Resolve one active workload or fail closed before provider observation."""

        normalized_workload_id = workload_id.strip()
        if not normalized_workload_id:
            raise ValueError("workload_id MUST be non-empty")
        observed_at = now or datetime.now(tz=UTC)
        if observed_at.tzinfo is None:
            raise ValueError("WARA scope time MUST be timezone-aware")

        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            snapshot = await self._active_snapshot(connection)
            snapshot_id, completed_at = _validate_snapshot(
                snapshot,
                now=observed_at,
                freshness_budget_seconds=self._config.freshness_budget_seconds,
            )
            await self._require_stable_generation(
                connection,
                snapshot_id=snapshot_id,
                completed_at=completed_at,
            )
            workload = await self._workload(connection, normalized_workload_id)
            ontology_release = _validate_workload(workload, now=observed_at)
            rows = await self._resources(
                connection,
                snapshot_id=snapshot_id,
                workload_id=normalized_workload_id,
            )

        resources = _resolve_resources(
            rows,
            ontology_release=ontology_release,
            maximum_resources=self._config.maximum_resources,
        )
        return WaraResolvedScope(
            workload_id=normalized_workload_id,
            ontology_release=ontology_release,
            inventory_generation=snapshot_id,
            resources=resources,
        )

    async def _active_snapshot(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
    ) -> Mapping[str, Any] | None:
        cursor = await connection.execute(
            "SELECT s.id, s.status, s.observation_kind, s.completed_at "
            "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
            "WHERE a.singleton=TRUE"
        )
        return await cursor.fetchone()

    async def _require_stable_generation(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        snapshot_id: str,
        completed_at: datetime,
    ) -> None:
        failure_cursor = await connection.execute(
            "SELECT 1 FROM inventory_snapshot WHERE id<>%s AND started_at>%s AND "
            "(status='failed' OR (status='collecting' AND "
            "started_at < NOW() - INTERVAL '30 minutes')) LIMIT 1",
            (snapshot_id, completed_at),
        )
        if await failure_cursor.fetchone() is not None:
            raise WaraScopeUnavailableError(
                "promoted inventory has a newer failed or abandoned collection"
            )
        overlay_cursor = await connection.execute(
            "SELECT COUNT(*) AS pending_changes FROM inventory_realtime_resource"
        )
        overlay = await overlay_cursor.fetchone()
        pending_changes = int(overlay["pending_changes"] or 0) if overlay is not None else 0
        if pending_changes:
            raise WaraScopeUnavailableError(
                "promoted inventory has unapplied realtime resource changes"
            )

    async def _workload(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        workload_id: str,
    ) -> Mapping[str, Any] | None:
        cursor = await connection.execute(
            "SELECT id, object_type, properties, catalog_digest FROM ontology_resource WHERE id=%s",
            (workload_id,),
        )
        return await cursor.fetchone()

    async def _resources(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        snapshot_id: str,
        workload_id: str,
    ) -> Sequence[Mapping[str, Any]]:
        cursor = await connection.execute(
            "SELECT l.to_id AS neutral_resource_id, "
            "l.catalog_digest AS link_catalog_digest, "
            "o.object_type, o.catalog_digest, r.resource_type, r.provider_ref "
            "FROM ontology_link l "
            "LEFT JOIN ontology_resource o ON o.id=l.to_id "
            "LEFT JOIN inventory_snapshot_resource r "
            "ON r.snapshot_id=%s AND r.resource_id=l.to_id "
            "WHERE l.from_id=%s AND l.link_type='workload_runs_on' "
            "ORDER BY l.to_id LIMIT %s",
            (snapshot_id, workload_id, self._config.maximum_resources + 1),
        )
        return await cursor.fetchall()

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _validate_snapshot(
    snapshot: Mapping[str, Any] | None,
    *,
    now: datetime,
    freshness_budget_seconds: int,
) -> tuple[str, datetime]:
    if snapshot is None:
        raise WaraScopeUnavailableError("promoted inventory snapshot is unavailable")
    snapshot_id = snapshot.get("id")
    completed_at = snapshot.get("completed_at")
    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id.strip()
        or not isinstance(completed_at, datetime)
        or completed_at.tzinfo is None
    ):
        raise WaraScopeUnavailableError("promoted inventory snapshot identity is invalid")
    if snapshot.get("observation_kind") != "observed":
        raise WaraScopeUnavailableError("promoted inventory is not an observed generation")
    if snapshot.get("status") != "active":
        raise WaraScopeUnavailableError("promoted inventory snapshot is not active")
    age_seconds = (now - completed_at).total_seconds()
    if age_seconds < 0 or age_seconds > freshness_budget_seconds:
        raise WaraScopeUnavailableError(
            "promoted inventory snapshot is outside its freshness bound"
        )
    return snapshot_id, completed_at


def _validate_workload(workload: Mapping[str, Any] | None, *, now: datetime) -> str:
    if workload is None or workload.get("object_type") != "Workload":
        raise WaraScopeUnavailableError("configured WARA workload is unavailable")
    ontology_release = workload.get("catalog_digest")
    if not isinstance(ontology_release, str) or _SHA256.fullmatch(ontology_release) is None:
        raise WaraScopeUnavailableError("configured WARA workload has no valid ontology release")
    properties = workload.get("properties")
    if isinstance(properties, str):
        try:
            properties = json.loads(properties)
        except json.JSONDecodeError as exc:
            raise WaraScopeUnavailableError(
                "configured WARA workload properties are invalid"
            ) from exc
    if not isinstance(properties, Mapping):
        raise WaraScopeUnavailableError("configured WARA workload properties are invalid")
    effective_from = _required_timestamp(properties.get("effective_from"), "effective_from")
    effective_to = _optional_timestamp(properties.get("effective_to"), "effective_to")
    if effective_from > now or (effective_to is not None and effective_to <= now):
        raise WaraScopeUnavailableError("configured WARA workload is not currently effective")
    return ontology_release


def _resolve_resources(
    rows: Sequence[Mapping[str, Any]],
    *,
    ontology_release: str,
    maximum_resources: int,
) -> tuple[WaraResolvedResource, ...]:
    if not rows:
        raise WaraScopeUnavailableError("configured WARA workload has no runtime resources")
    if len(rows) > maximum_resources:
        raise WaraScopeUnavailableError("configured WARA workload exceeds its resource bound")

    resources: list[WaraResolvedResource] = []
    for row in rows:
        neutral_id = row.get("neutral_resource_id")
        provider_id = row.get("provider_ref")
        if (
            not isinstance(neutral_id, str)
            or not neutral_id.strip()
            or row.get("link_catalog_digest") != ontology_release
            or row.get("object_type") != "Resource"
            or row.get("catalog_digest") != ontology_release
            or not isinstance(row.get("resource_type"), str)
            or not isinstance(provider_id, str)
        ):
            raise WaraScopeUnavailableError(
                "configured WARA workload resource coverage is incomplete"
            )
        provider_type = arm_id_to_type(provider_id)
        if provider_type is None:
            raise WaraScopeUnavailableError(
                "configured WARA workload resource has no exact Azure identity"
            )
        resources.append(
            WaraResolvedResource(
                neutral_resource_id=neutral_id,
                provider_resource_id=provider_id,
                provider_resource_type=provider_type,
            )
        )
    provider_ids = [item.provider_resource_id.casefold() for item in resources]
    if len(provider_ids) != len(set(provider_ids)):
        raise WaraScopeUnavailableError(
            "configured WARA workload contains duplicate Azure identities"
        )
    return tuple(sorted(resources, key=lambda item: item.provider_resource_id))


def _required_timestamp(value: object, field_name: str) -> datetime:
    parsed = _optional_timestamp(value, field_name)
    if parsed is None:
        raise WaraScopeUnavailableError(f"configured WARA workload {field_name} is required")
    return parsed


def _optional_timestamp(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WaraScopeUnavailableError(f"configured WARA workload {field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WaraScopeUnavailableError(
            f"configured WARA workload {field_name} is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise WaraScopeUnavailableError(f"configured WARA workload {field_name} is invalid")
    return parsed


__all__ = [
    "PostgresWaraScopeSource",
    "PostgresWaraScopeSourceConfig",
    "WaraResolvedResource",
    "WaraResolvedScope",
    "WaraScopeUnavailableError",
]
