"""Read principal-safe OI-12 aggregate evidence from PostgreSQL."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.operational_instance_certification import (
    OperationalCertificationSnapshot,
    build_operational_certification_snapshot,
)

_SNAPSHOT_QUERY = """
WITH observed AS (
    SELECT clock_timestamp() AS measured_at
),
active AS (
    SELECT snapshot.completed_at
    FROM inventory_active AS active_pointer
    JOIN inventory_snapshot AS snapshot
        ON snapshot.id = active_pointer.snapshot_id
    WHERE active_pointer.singleton
),
cursor_health AS (
    SELECT MAX(updated_at) AS updated_at
    FROM state_kv
    WHERE key LIKE 'inventory_delta_cursor:%'
),
archive AS (
    SELECT
        COUNT(*) AS total_count,
        COUNT(*) FILTER (
            WHERE manifest.coverage_complete
                AND EXISTS (
                    SELECT 1
                    FROM operational_archive_verification_receipt AS verification
                    WHERE verification.manifest_digest = manifest.manifest_digest
                        AND verification.verified
                )
        ) AS complete_count
    FROM operational_archive_manifest AS manifest
),
restore AS (
    SELECT
        COUNT(*) AS total_count,
        COUNT(*) FILTER (WHERE passed) AS passed_count
    FROM operational_archive_restore_receipt
),
latest_recovery AS (
    SELECT
        EXTRACT(EPOCH FROM (successful.completed_at - failed.completed_at))
            AS recovery_seconds
    FROM inventory_snapshot AS failed
    CROSS JOIN LATERAL (
        SELECT candidate.completed_at
        FROM inventory_snapshot AS candidate
        WHERE candidate.status IN ('active', 'superseded')
            AND candidate.completed_at > failed.completed_at
        ORDER BY candidate.completed_at
        LIMIT 1
    ) AS successful
    WHERE failed.status = 'failed'
        AND failed.completed_at IS NOT NULL
    ORDER BY failed.completed_at DESC
    LIMIT 1
)
SELECT
    observed.measured_at,
    ontology_status.value AS ontology_status,
    pg_database_size(current_database()) AS database_bytes,
    CASE
        WHEN active.completed_at IS NULL OR active.completed_at > observed.measured_at THEN NULL
        ELSE EXTRACT(EPOCH FROM (observed.measured_at - active.completed_at))
    END AS freshness_seconds,
    CASE
        WHEN cursor_health.updated_at IS NULL
            OR cursor_health.updated_at > observed.measured_at THEN NULL
        ELSE EXTRACT(EPOCH FROM (observed.measured_at - cursor_health.updated_at))
    END AS lag_seconds,
    collection_health.value AS collection_health,
    archive.total_count AS rollup_total_count,
    archive.complete_count AS rollup_complete_count,
    restore.total_count AS restore_total_count,
    restore.passed_count AS restore_passed_count,
    latest_recovery.recovery_seconds AS provider_failure_recovery_seconds
FROM observed
LEFT JOIN active ON TRUE
LEFT JOIN cursor_health ON TRUE
LEFT JOIN state_kv AS ontology_status
    ON ontology_status.key = 'inventory-ontology:status'
LEFT JOIN state_kv AS collection_health
    ON collection_health.key = 'inventory-collection-health'
CROSS JOIN archive
CROSS JOIN restore
LEFT JOIN latest_recovery ON TRUE
"""


@dataclass(frozen=True, slots=True)
class PostgresOperationalCertificationSourceConfig:
    """Configure bounded read-only OI-12 aggregate collection."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("operational certification source DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("operational certification source timeouts MUST be positive")

    @property
    def psycopg_dsn(self) -> str:
        """Return the service DSN in psycopg's accepted URI form."""

        return self.dsn.replace("postgresql+psycopg://", "postgresql://", 1)


class PostgresOperationalCertificationSource:
    """Read principal-safe OI-12 aggregates from one PostgreSQL snapshot."""

    def __init__(self, *, config: PostgresOperationalCertificationSourceConfig) -> None:
        self._config = config

    async def capture(self) -> OperationalCertificationSnapshot:
        """Capture one sanitized snapshot or fail before assigning a release."""

        async with await self._connect() as connection:
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(_SNAPSHOT_QUERY)
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("operational certification aggregate query returned no row")
        return _snapshot_from_row(row)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.psycopg_dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )


def _snapshot_from_row(row: Mapping[str, object]) -> OperationalCertificationSnapshot:
    measured_at = row.get("measured_at")
    if not isinstance(measured_at, datetime):
        raise ValueError("operational certification database time is unavailable")
    ontology_status = _mapping(row.get("ontology_status"))
    ontology_release_digest = ontology_status.get("ontology_release_digest")
    if not isinstance(ontology_release_digest, str):
        raise ValueError("operational certification exact ontology release is unavailable")
    collection_health = _mapping(row.get("collection_health"))
    provider_pressure = _mapping(collection_health.get("provider_pressure"))
    remaining_ratio = _decimal_value(provider_pressure.get("budget_remaining_ratio"))
    pressure_state = provider_pressure.get("state")
    retry_after_seconds = _decimal_value(provider_pressure.get("retry_after_seconds"))
    api_pressure_ratio = (
        Decimal(1) - remaining_ratio
        if remaining_ratio is not None
        else Decimal(0)
        if pressure_state == "healthy" and retry_after_seconds is None
        else None
    )
    return build_operational_certification_snapshot(
        measured_at=measured_at,
        ontology_release_digest=ontology_release_digest,
        database_bytes=_optional_int(row.get("database_bytes")),
        freshness_seconds=_decimal_value(row.get("freshness_seconds")),
        api_pressure_ratio=api_pressure_ratio,
        lag_seconds=_decimal_value(row.get("lag_seconds")),
        rollup_total_count=_required_int(row.get("rollup_total_count"), "rollup total"),
        rollup_complete_count=_required_int(row.get("rollup_complete_count"), "rollup complete"),
        restore_total_count=_required_int(row.get("restore_total_count"), "restore total"),
        restore_passed_count=_required_int(row.get("restore_passed_count"), "restore passed"),
        provider_failure_recovery_seconds=_decimal_value(
            row.get("provider_failure_recovery_seconds")
        ),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, Mapping) else {}


def _decimal_value(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _required_int(value: object, name: str) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise ValueError(f"operational certification {name} count is unavailable")
    return parsed


__all__ = [
    "PostgresOperationalCertificationSource",
    "PostgresOperationalCertificationSourceConfig",
]
