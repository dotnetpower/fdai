"""Aggregate-only PostgreSQL inventory for prospective cohort evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from fdai.core.measurement.cohort_claim_policy import (
    CohortClaimPolicy,
    require_commit_revision,
)
from fdai_service_contracts.baseline_cohort import CohortArm
from psycopg.rows import dict_row

_METRIC_KIND = "measurement.cohort.metric.v1"
_GUARD_KIND = "measurement.cohort.guard.v1"


@dataclass(frozen=True, slots=True)
class CohortEvidenceInventory:
    """Repository-safe counts for one bounded operational evidence window."""

    window_start: datetime
    window_end: datetime
    candidate_action_outcomes: int
    candidate_resolved_incidents: int
    candidate_changes: int
    candidate_cost_units: int
    metric_counts: Mapping[str, Mapping[str, int]]
    guard_counts: Mapping[str, Mapping[str, int]]
    minimum_sample_size: int
    ready: bool
    missing: tuple[str, ...]

    def to_log_record(self) -> dict[str, object]:
        """Return aggregate-only fields safe for workflow and platform logs."""

        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "candidate_action_outcomes": self.candidate_action_outcomes,
            "candidate_resolved_incidents": self.candidate_resolved_incidents,
            "candidate_changes": self.candidate_changes,
            "candidate_cost_units": self.candidate_cost_units,
            "metric_counts": {
                arm: dict(sorted(counts.items()))
                for arm, counts in sorted(self.metric_counts.items())
            },
            "guard_counts": {
                arm: dict(sorted(counts.items()))
                for arm, counts in sorted(self.guard_counts.items())
            },
            "minimum_sample_size": self.minimum_sample_size,
            "ready": self.ready,
            "missing": list(self.missing),
        }


class PostgresCohortEvidenceInventorySource:
    """Read only aggregate cohort availability from the private state store."""

    def __init__(
        self,
        *,
        dsn: str,
        policy: CohortClaimPolicy,
        expected_revision: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn:
            raise ValueError("cohort inventory dsn MUST be non-empty")
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        self._policy = policy
        self._expected_revision = require_commit_revision(expected_revision)
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def inventory(self, *, evaluated_at: datetime) -> CohortEvidenceInventory:
        """Count protocol-bound evidence without returning operational payloads."""

        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("cohort inventory evaluation time MUST include a timezone")
        window_end = evaluated_at.astimezone(UTC)
        window_start = window_end - timedelta(seconds=self._policy.maximum_window_seconds)
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute("SET TRANSACTION READ ONLY")
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._statement_timeout_ms),),
                )
                candidates = await self._candidate_counts(
                    connection,
                    window_start=window_start,
                    window_end=window_end,
                )
                metric_rows = await self._measure_counts(
                    connection,
                    action_kind=_METRIC_KIND,
                    identifier_key="metric_id",
                    window_start=window_start,
                    window_end=window_end,
                )
                guard_rows = await self._measure_counts(
                    connection,
                    action_kind=_GUARD_KIND,
                    identifier_key="guard_id",
                    window_start=window_start,
                    window_end=window_end,
                )

        metric_counts = _required_counts(
            metric_rows,
            required=self._policy.required_metric_ids,
            allowed_sources=_source_binding_index(self._policy, metrics=True),
        )
        guard_counts = _required_counts(
            guard_rows,
            required=self._policy.required_guard_ids,
            allowed_sources=_source_binding_index(self._policy, metrics=False),
        )
        missing = _missing(
            metric_counts=metric_counts,
            guard_counts=guard_counts,
            minimum=self._policy.minimum_sample_size,
        )
        return CohortEvidenceInventory(
            window_start=window_start,
            window_end=window_end,
            candidate_action_outcomes=int(candidates["candidate_action_outcomes"]),
            candidate_resolved_incidents=int(candidates["candidate_resolved_incidents"]),
            candidate_changes=int(candidates["candidate_changes"]),
            candidate_cost_units=int(candidates["candidate_cost_units"]),
            metric_counts=metric_counts,
            guard_counts=guard_counts,
            minimum_sample_size=self._policy.minimum_sample_size,
            ready=not missing,
            missing=missing,
        )

    async def _candidate_counts(
        self,
        connection: psycopg.AsyncConnection[Mapping[str, Any]],
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> Mapping[str, Any]:
        cursor = await connection.execute(
            """
            SELECT
              COUNT(DISTINCT NULLIF(entry->>'event_id', ''))
                FILTER (WHERE action_kind = 'measurement.action_outcome.v1')
                AS candidate_action_outcomes,
              COUNT(DISTINCT NULLIF(entry->>'incident_id', ''))
                FILTER (
                  WHERE action_kind = 'incident.transition'
                    AND entry->>'to_state' = 'resolved'
                ) AS candidate_resolved_incidents,
              COUNT(DISTINCT NULLIF(entry->>'change_id', ''))
                FILTER (
                  WHERE NULLIF(entry->>'change_request_time', '') IS NOT NULL
                    AND NULLIF(entry->>'merge_time', '') IS NOT NULL
                ) AS candidate_changes,
              COUNT(DISTINCT NULLIF(entry->>'unit_id', ''))
                FILTER (
                  WHERE NULLIF(entry->>'attributable_cost_usd', '') IS NOT NULL
                ) AS candidate_cost_units
            FROM audit_log
            WHERE created_at >= %s
              AND created_at <= %s
              AND entry->>'fdai_revision' = %s
            """,
            (window_start, window_end, self._expected_revision),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("cohort inventory aggregate query returned no row")
        return row

    async def _measure_counts(
        self,
        connection: psycopg.AsyncConnection[Mapping[str, Any]],
        *,
        action_kind: str,
        identifier_key: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Mapping[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT
              entry->>'arm' AS arm,
              entry->>%s AS measure_id,
              entry->>'source_binding_id' AS source_binding_id,
              entry->>'source_workflow_path' AS source_workflow_path,
              COUNT(DISTINCT NULLIF(entry->>'source_cluster_digest', '')) AS sample_count
            FROM audit_log
            WHERE action_kind = %s
              AND created_at >= %s
              AND created_at <= %s
              AND entry->>'measurement_protocol_digest' = %s
              AND entry->>'measurement_protocol_version' = %s
              AND entry->>'fdai_revision' = %s
              AND entry->>'synthetic' = 'false'
              AND entry->>'source_cluster_digest' ~ '^sha256:[0-9a-f]{64}$'
              AND entry->>'observation_digest' ~ '^sha256:[0-9a-f]{64}$'
              AND CASE
                WHEN entry->>'observed_at' ~
                  '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+([+]00:00|Z)$'
                THEN (entry->>'observed_at')::TIMESTAMPTZ >= %s
                  AND (entry->>'observed_at')::TIMESTAMPTZ <= %s
                ELSE FALSE
              END
              AND (
                (%s = 'metric_id' AND jsonb_typeof(entry->'value') = 'number'
                  AND (entry->>'value')::NUMERIC >= 0)
                OR (%s = 'guard_id' AND jsonb_typeof(entry->'breached') = 'boolean')
              )
            GROUP BY 1, 2, 3, 4
            """,
            (
                identifier_key,
                action_kind,
                window_start,
                window_end,
                self._policy.measurement_protocol_digest,
                self._policy.measurement_protocol_version,
                self._expected_revision,
                window_start,
                window_end,
                identifier_key,
                identifier_key,
            ),
        )
        return list(await cursor.fetchall())


def _required_counts(
    rows: list[Mapping[str, Any]],
    *,
    required: tuple[str, ...],
    allowed_sources: Mapping[tuple[str, str], tuple[str, str]],
) -> Mapping[str, Mapping[str, int]]:
    counts = {arm.value: {identifier: 0 for identifier in required} for arm in CohortArm}
    for row in rows:
        arm = row.get("arm")
        measure_id = row.get("measure_id")
        source_binding_id = row.get("source_binding_id")
        source_workflow_path = row.get("source_workflow_path")
        sample_count = row.get("sample_count")
        if (
            isinstance(arm, str)
            and arm in counts
            and isinstance(measure_id, str)
            and measure_id in counts[arm]
            and isinstance(sample_count, int)
            and sample_count >= 0
            and allowed_sources.get((arm, measure_id)) == (source_binding_id, source_workflow_path)
        ):
            counts[arm][measure_id] = sample_count
    return counts


def _source_binding_index(
    policy: CohortClaimPolicy,
    *,
    metrics: bool,
) -> Mapping[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for arm, bindings in policy.exporter_measure_bindings:
        for binding in bindings:
            measure_ids = binding.metric_ids if metrics else binding.guard_ids
            for measure_id in measure_ids:
                result[(arm, measure_id)] = (
                    binding.source_id,
                    binding.workflow_path,
                )
    return result


def _missing(
    *,
    metric_counts: Mapping[str, Mapping[str, int]],
    guard_counts: Mapping[str, Mapping[str, int]],
    minimum: int,
) -> tuple[str, ...]:
    missing = [
        f"{arm}:metric:{identifier}:{count}/{minimum}"
        for arm, counts in metric_counts.items()
        for identifier, count in counts.items()
        if count < minimum
    ]
    missing.extend(
        f"{arm}:guard:{identifier}:{count}/{minimum}"
        for arm, counts in guard_counts.items()
        for identifier, count in counts.items()
        if count < minimum
    )
    return tuple(sorted(missing))


__all__ = [
    "CohortEvidenceInventory",
    "PostgresCohortEvidenceInventorySource",
]
