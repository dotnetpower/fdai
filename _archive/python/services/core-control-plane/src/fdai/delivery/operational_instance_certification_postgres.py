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
    SELECT
        snapshot.id,
        snapshot.source,
        snapshot.observation_kind
    FROM inventory_active AS active_pointer
    JOIN inventory_snapshot AS snapshot
        ON snapshot.id = active_pointer.snapshot_id
    WHERE active_pointer.singleton
),
ontology AS (
    SELECT value
    FROM state_kv
    WHERE key = 'inventory-ontology:status'
),
latest_coverage AS (
    SELECT
        jsonb_array_length(coverage.manifest_digests)::bigint AS total_count,
        CASE
            WHEN coverage.complete
                AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(coverage.manifest_digests) AS item(digest)
                    LEFT JOIN operational_archive_manifest AS manifest
                        ON manifest.manifest_digest = item.digest
                    CROSS JOIN ontology
                    WHERE manifest.manifest_digest IS NULL
                        OR NOT (
                            COALESCE(
                                manifest.record -> 'ontology_release_digests',
                                '[]'::jsonb
                            ) ? (ontology.value ->> 'ontology_release_digest')
                        )
                )
            THEN jsonb_array_length(coverage.manifest_digests)::bigint
            ELSE 0::bigint
        END AS complete_count
    FROM operational_archive_coverage_receipt AS coverage
    ORDER BY coverage.recorded_at DESC, coverage.receipt_digest DESC
    LIMIT 1
),
latest_restore AS (
    SELECT
        1::bigint AS total_count,
        CASE
            WHEN restore.passed
                AND verification.verified
                AND COALESCE(
                    manifest.record -> 'ontology_release_digests',
                    '[]'::jsonb
                ) ? (ontology.value ->> 'ontology_release_digest')
            THEN 1::bigint
            ELSE 0::bigint
        END AS passed_count
    FROM operational_archive_restore_receipt AS restore
    JOIN operational_archive_verification_receipt AS verification
        ON verification.receipt_digest = restore.verification_receipt_digest
        AND verification.manifest_digest = restore.manifest_digest
    JOIN operational_archive_manifest AS manifest
        ON manifest.manifest_digest = restore.manifest_digest
    CROSS JOIN ontology
    ORDER BY restore.sampled_at DESC, restore.receipt_digest DESC
    LIMIT 1
),
latest_failure AS (
    SELECT
        failed.source,
        failed.observation_kind,
        failed.scopes,
        failed.resource_types,
        failed.completed_at
    FROM inventory_snapshot AS failed
    JOIN active AS current
        ON current.source = failed.source
        AND current.observation_kind = failed.observation_kind
    WHERE failed.status = 'failed'
        AND failed.completed_at IS NOT NULL
        AND failed.failure_code <> 'invalid_data'
    ORDER BY failed.completed_at DESC
    LIMIT 1
),
latest_recovery AS (
    SELECT
        CASE
            WHEN successful.completed_at IS NULL THEN NULL
            ELSE EXTRACT(EPOCH FROM (successful.completed_at - failed.completed_at))
        END
            AS recovery_seconds
    FROM latest_failure AS failed
    LEFT JOIN LATERAL (
        SELECT candidate.completed_at
        FROM inventory_snapshot AS candidate
        WHERE candidate.status IN ('active', 'superseded')
            AND candidate.completed_at > failed.completed_at
            AND candidate.source = failed.source
            AND candidate.observation_kind = failed.observation_kind
            AND candidate.scopes = failed.scopes
            AND candidate.resource_types = failed.resource_types
        ORDER BY candidate.completed_at
        LIMIT 1
    ) AS successful ON TRUE
)
SELECT
    observed.measured_at,
    active.id AS active_generation,
    ontology_status.value AS ontology_status,
    pg_database_size(current_database()) AS database_bytes,
    collection_health.value AS collection_health,
    COALESCE(latest_coverage.total_count, 0::bigint) AS rollup_total_count,
    COALESCE(latest_coverage.complete_count, 0::bigint) AS rollup_complete_count,
    COALESCE(latest_restore.total_count, 0::bigint) AS restore_total_count,
    COALESCE(latest_restore.passed_count, 0::bigint) AS restore_passed_count,
    latest_recovery.recovery_seconds AS provider_failure_recovery_seconds
FROM observed
LEFT JOIN active ON TRUE
LEFT JOIN state_kv AS ontology_status
    ON ontology_status.key = 'inventory-ontology:status'
LEFT JOIN state_kv AS collection_health
    ON collection_health.key = 'inventory-collection-health'
LEFT JOIN latest_coverage ON TRUE
LEFT JOIN latest_restore ON TRUE
LEFT JOIN latest_recovery ON TRUE
"""


class OperationalCertificationGenerationPendingError(ValueError):
    """Report that inventory and ontology projection have not converged yet."""


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
    active_generation = row.get("active_generation")
    if (
        not isinstance(active_generation, str)
        or ontology_status.get("generation") != active_generation
        or ontology_status.get("status") != "available"
    ):
        raise OperationalCertificationGenerationPendingError(
            "operational certification inventory and ontology generations do not match"
        )
    ontology_release_digest = ontology_status.get("ontology_release_digest")
    if not isinstance(ontology_release_digest, str):
        raise ValueError("operational certification exact ontology release is unavailable")
    collection_health = _mapping(row.get("collection_health"))
    freshness = _mapping(collection_health.get("freshness"))
    cursor = _mapping(collection_health.get("cursor"))
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
        freshness_seconds=_decimal_value(freshness.get("age_seconds")),
        api_pressure_ratio=api_pressure_ratio,
        lag_seconds=_decimal_value(cursor.get("lag_seconds")),
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
    "OperationalCertificationGenerationPendingError",
    "PostgresOperationalCertificationSource",
    "PostgresOperationalCertificationSourceConfig",
]
