"""PostgreSQL persistence for Cost Governance activation and evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import psycopg
from fdai_service_contracts import CostAnalyticsRunReceipt
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.shared.providers.cost_governance import (
    CostCollectionCursor,
    CostObservation,
    CostObservationPage,
    CostPackageActivation,
)


@dataclass(frozen=True, slots=True)
class PostgresCostGovernanceConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("Cost Governance DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Cost Governance database timeouts MUST be positive")


class PostgresCostGovernanceStore:
    """CAS activation/cursors and append immutable cost facts."""

    def __init__(self, *, config: PostgresCostGovernanceConfig) -> None:
        self._config = config

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None:
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT vertical_id, package_id, available, enabled, previously_enabled,
                       availability_reasons, package_version, image_digest,
                       asset_manifest_digest, semantic_profile_digest, revision,
                       effective_at, ontology_release_id, ontology_release_digest,
                       source_authority
                  FROM vertical_package_activation
                 WHERE package_id = %s
                """,
                (package_id,),
            )
            row = await cursor.fetchone()
        return _activation(row) if row is not None else None

    async def compare_and_set_cost_activation(
        self,
        activation: CostPackageActivation,
        *,
        expected_revision: int,
    ) -> bool:
        """Persist one activation transition without deleting retained data."""

        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                if expected_revision == 0:
                    inserted = await conn.execute(
                        """
                        INSERT INTO vertical_package_activation (
                            package_id, vertical_id, available, enabled, previously_enabled,
                            availability_reasons, package_version, image_digest,
                            asset_manifest_digest, semantic_profile_digest, revision,
                            effective_at, ontology_release_id, ontology_release_digest,
                            source_authority, updated_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            1, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (package_id) DO NOTHING
                        """,
                        (
                            activation.package_id,
                            activation.vertical_id,
                            activation.available,
                            activation.enabled,
                            activation.previously_enabled,
                            Jsonb(list(activation.availability_reasons)),
                            activation.package_version,
                            activation.image_digest,
                            activation.asset_manifest_digest,
                            activation.semantic_profile_digest,
                            activation.effective_at,
                            activation.ontology_release_id,
                            activation.ontology_release_digest,
                            activation.source_authority,
                            activation.effective_at,
                        ),
                    )
                    if inserted.rowcount == 1:
                        return True
                updated = await conn.execute(
                    """
                    UPDATE vertical_package_activation
                       SET vertical_id = %s,
                           available = %s,
                           enabled = %s,
                           previously_enabled = enabled,
                           availability_reasons = %s,
                           package_version = %s,
                           image_digest = %s,
                           asset_manifest_digest = %s,
                           semantic_profile_digest = %s,
                           revision = revision + 1,
                           effective_at = %s,
                           ontology_release_id = %s,
                           ontology_release_digest = %s,
                           source_authority = %s,
                           updated_at = %s
                     WHERE package_id = %s
                       AND revision = %s
                    """,
                    (
                        activation.vertical_id,
                        activation.available,
                        activation.enabled,
                        Jsonb(list(activation.availability_reasons)),
                        activation.package_version,
                        activation.image_digest,
                        activation.asset_manifest_digest,
                        activation.semantic_profile_digest,
                        activation.effective_at,
                        activation.ontology_release_id,
                        activation.ontology_release_digest,
                        activation.source_authority,
                        activation.effective_at,
                        activation.package_id,
                        expected_revision,
                    ),
                )
                return updated.rowcount == 1

    async def append_cost_analytics_snapshot(
        self,
        *,
        snapshot_id: str,
        package_id: str,
        scope_id: str,
        observed_at: datetime,
        source_authority: str,
        complete: bool,
        payload: Mapping[str, object],
        evidence_digest: str,
        retention_until: datetime,
    ) -> bool:
        """Append one immutable disclosure-safe analytics snapshot."""

        async with await self._connect() as conn:
            await self._timeout(conn)
            inserted = await conn.execute(
                """
                INSERT INTO cost_governance_analytics_snapshot (
                    snapshot_id, package_id, scope_id, observed_at,
                    source_authority, complete, payload, evidence_digest,
                    retention_until
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                (
                    snapshot_id,
                    package_id,
                    scope_id,
                    observed_at,
                    source_authority,
                    complete,
                    Jsonb(dict(payload)),
                    evidence_digest,
                    retention_until,
                ),
            )
        return inserted.rowcount == 1

    async def append_cost_analytics_run_receipt(
        self,
        receipt: CostAnalyticsRunReceipt,
        *,
        scope_id: str,
    ) -> bool:
        """Append one content-free terminal analytics receipt idempotently."""

        if not scope_id:
            raise ValueError("Cost Analytics receipt scope MUST be non-empty")
        scope_digest = f"sha256:{hashlib.sha256(scope_id.encode()).hexdigest()}"
        if receipt.scope_digest != scope_digest:
            raise ValueError("Cost Analytics receipt scope digest does not match")
        async with await self._connect() as conn:
            await self._timeout(conn)
            inserted = await conn.execute(
                """
                INSERT INTO cost_governance_analytics_run_receipt (
                    run_id, receipt_digest, package_id, scope_id, scope_digest,
                    venue, window_start_at, window_end_at, started_at, finished_at,
                    status, sources, observation_count, trend_point_count,
                    budget_count, recommendation_count, utilization_count,
                    limitations, failure_reason, snapshot_id
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    receipt.run_id,
                    receipt.receipt_digest,
                    "cost-governance",
                    scope_id,
                    receipt.scope_digest,
                    receipt.venue,
                    receipt.window_start_at,
                    receipt.window_end_at,
                    receipt.started_at,
                    receipt.finished_at,
                    receipt.status.value,
                    Jsonb([item.model_dump(mode="json") for item in receipt.sources]),
                    receipt.observation_count,
                    receipt.trend_point_count,
                    receipt.budget_count,
                    receipt.recommendation_count,
                    receipt.utilization_count,
                    Jsonb(list(receipt.limitations)),
                    receipt.failure_reason,
                    receipt.snapshot_id,
                ),
            )
            if inserted.rowcount == 1:
                return True
            existing = await conn.execute(
                """
                SELECT receipt_digest
                  FROM cost_governance_analytics_run_receipt
                 WHERE run_id = %s
                """,
                (receipt.run_id,),
            )
            row = await existing.fetchone()
            if row is None or str(row["receipt_digest"]) != receipt.receipt_digest:
                raise RuntimeError("Cost Analytics run identity conflicts with retained evidence")
        return False

    async def cost_budget_data_available(self) -> bool:
        """Return whether the latest analytics snapshot contains a budget."""

        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT COALESCE(
                    jsonb_array_length(payload -> 'budgets') > 0,
                    FALSE
                ) AS available
                  FROM cost_governance_analytics_snapshot
                 ORDER BY observed_at DESC, snapshot_id DESC
                 LIMIT 1
                """
            )
            row = await cursor.fetchone()
        return bool(row and row["available"])

    async def current_cost_analytics_snapshot_available(
        self,
        *,
        scope_id: str,
        now: datetime,
        freshness: timedelta,
    ) -> bool:
        """Return whether one retained snapshot is current for the exact scope."""

        if now.tzinfo is None or freshness <= timedelta(0):
            raise ValueError("Cost Analytics freshness inputs are invalid")
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                      FROM cost_governance_analytics_snapshot
                     WHERE scope_id = %s
                       AND observed_at >= %s
                       AND retention_until > %s
                ) AS available
                """,
                (scope_id, now - freshness, now),
            )
            row = await cursor.fetchone()
        return bool(row and row["available"])

    async def read_recent_complete_cost_observations(
        self,
        *,
        package_id: str,
        ontology_release_digest: str,
        limit: int,
    ) -> tuple[CostObservation, ...]:
        """Read a bounded restart baseline in chronological order."""

        if not 1 <= limit <= 1000:
            raise ValueError("cost observation hydration limit MUST be in [1, 1000]")
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT *
                  FROM (
                    SELECT observation.observation_id, observation.package_id,
                           observation.scope_id, observation.service_id,
                           observation.amount, observation.currency,
                           observation.event_start_at, observation.event_end_at,
                           observation.observed_at, observation.recorded_at,
                           observation.source_authority, observation.source_uri,
                           observation.completeness, observation.ontology_release_id,
                           observation.ontology_release_digest,
                           observation.evidence_digest, observation.retention_until
                      FROM cost_observation AS observation
                      JOIN cost_observation_current AS current
                        ON current.observation_id = observation.observation_id
                     WHERE observation.package_id = %s
                       AND observation.ontology_release_digest = %s
                       AND observation.completeness = 1
                       AND observation.currency = 'USD'
                       AND observation.retention_until > CURRENT_TIMESTAMP
                     ORDER BY observation.observed_at DESC,
                              observation.observation_id DESC
                     LIMIT %s
                  ) AS recent
                 ORDER BY observed_at, observation_id
                """,
                (package_id, ontology_release_digest, limit),
            )
            rows: Sequence[dict[str, Any]] = await cursor.fetchall()
        return tuple(_observation(row) for row in rows)

    async def read_cost_cursor(
        self,
        package_id: str,
        scope_id: str,
    ) -> CostCollectionCursor | None:
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT package_id, scope_id, revision, analysis_revision, resume_token,
                       coverage_through_at, retention_floor_at, last_published_at,
                       last_published_observation_id
                  FROM cost_collection_cursor
                 WHERE package_id = %s AND scope_id = %s
                """,
                (package_id, scope_id),
            )
            row = await cursor.fetchone()
        return _cursor(row) if row is not None else None

    async def append_cost_page(
        self,
        page: CostObservationPage,
        *,
        package_id: str,
        scope_id: str,
        expected_revision: int,
        coverage_through_at: datetime,
        retention_floor_at: datetime,
    ) -> bool:
        """Atomically append one page and CAS its durable cursor."""

        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                await conn.execute(
                    """
                    INSERT INTO cost_collection_cursor (
                        package_id, scope_id, revision, resume_token,
                        coverage_through_at, retention_floor_at, updated_at
                    )
                    VALUES (%s, %s, 0, NULL, %s, %s, %s)
                    ON CONFLICT (package_id, scope_id) DO NOTHING
                    """,
                    (
                        package_id,
                        scope_id,
                        retention_floor_at,
                        retention_floor_at,
                        page.collected_at,
                    ),
                )
                locked = await conn.execute(
                    """
                    SELECT revision, coverage_through_at
                      FROM cost_collection_cursor
                     WHERE package_id = %s AND scope_id = %s
                     FOR UPDATE
                    """,
                    (package_id, scope_id),
                )
                row = await locked.fetchone()
                if (
                    row is None
                    or cast(int, row["revision"]) != expected_revision
                    or coverage_through_at < cast(datetime, row["coverage_through_at"])
                ):
                    return False
                if page.observations:
                    sql_cursor = conn.cursor()
                    await sql_cursor.executemany(
                        """
                        INSERT INTO cost_observation (
                            observation_id, package_id, scope_id, service_id, amount,
                            currency, event_start_at, event_end_at, observed_at,
                            recorded_at, source_authority, source_uri, completeness,
                            ontology_release_id, ontology_release_digest, evidence_digest,
                            retention_until
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (observation_id) DO NOTHING
                        """,
                        tuple(_observation_values(item) for item in page.observations),
                    )
                    await sql_cursor.executemany(
                        """
                        INSERT INTO cost_observation_current (
                            package_id, scope_id, service_id, currency, event_day,
                            observation_id, recorded_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (
                            package_id, scope_id, service_id, currency, event_day
                        ) DO UPDATE
                           SET observation_id = EXCLUDED.observation_id,
                               recorded_at = EXCLUDED.recorded_at
                         WHERE (
                             EXCLUDED.recorded_at, EXCLUDED.observation_id
                         ) > (
                             cost_observation_current.recorded_at,
                             cost_observation_current.observation_id
                         )
                        """,
                        tuple(_current_observation_values(item) for item in page.observations),
                    )
                updated = await conn.execute(
                    """
                    UPDATE cost_collection_cursor
                       SET revision = revision + 1,
                           resume_token = %s,
                           coverage_through_at = %s,
                           retention_floor_at = GREATEST(retention_floor_at, %s),
                           updated_at = %s
                     WHERE package_id = %s
                       AND scope_id = %s
                       AND revision = %s
                    """,
                    (
                        page.next_resume_token,
                        coverage_through_at,
                        retention_floor_at,
                        page.collected_at,
                        package_id,
                        scope_id,
                        expected_revision,
                    ),
                )
                return updated.rowcount == 1

    async def read_cost_observations(
        self,
        *,
        package_id: str,
        scope_id: str,
        since: datetime,
        limit: int,
    ) -> tuple[CostObservation, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("cost observation read limit MUST be in [1, 1000]")
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT observation.observation_id, observation.package_id,
                       observation.scope_id, observation.service_id,
                       observation.amount, observation.currency,
                       observation.event_start_at, observation.event_end_at,
                       observation.observed_at, observation.recorded_at,
                       observation.source_authority, observation.source_uri,
                       observation.completeness, observation.ontology_release_id,
                       observation.ontology_release_digest,
                       observation.evidence_digest, observation.retention_until
                  FROM cost_observation AS observation
                  JOIN cost_observation_current AS current
                    ON current.observation_id = observation.observation_id
                 WHERE observation.package_id = %s
                   AND observation.scope_id = %s
                   AND observation.observed_at >= %s
                 ORDER BY observation.observed_at, observation.observation_id
                 LIMIT %s
                """,
                (package_id, scope_id, since, limit),
            )
            rows: Sequence[dict[str, Any]] = await cursor.fetchall()
        return tuple(_observation(row) for row in rows)

    async def advance_cost_analysis_cursor(
        self,
        *,
        package_id: str,
        scope_id: str,
        observation_id: str,
        observed_at: datetime,
        expected_analysis_revision: int,
    ) -> bool:
        """CAS the durable single-publish position after broker acceptance."""

        async with await self._connect() as conn:
            await self._timeout(conn)
            updated = await conn.execute(
                """
                UPDATE cost_collection_cursor
                   SET analysis_revision = analysis_revision + 1,
                       last_published_at = %s,
                       last_published_observation_id = %s,
                       updated_at = %s
                 WHERE package_id = %s
                   AND scope_id = %s
                   AND analysis_revision = %s
                   AND (
                       last_published_at IS NULL
                       OR (last_published_at, last_published_observation_id) < (%s, %s)
                   )
                """,
                (
                    observed_at,
                    observation_id,
                    observed_at,
                    package_id,
                    scope_id,
                    expected_analysis_revision,
                    observed_at,
                    observation_id,
                ),
            )
            return updated.rowcount == 1

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _activation(row: dict[str, Any]) -> CostPackageActivation:
    return CostPackageActivation(
        vertical_id=str(row["vertical_id"]),
        package_id=str(row["package_id"]),
        available=cast(bool, row["available"]),
        enabled=cast(bool, row["enabled"]),
        availability_reasons=tuple(
            str(reason) for reason in cast(list[object], row["availability_reasons"])
        ),
        package_version=str(row["package_version"]),
        image_digest=str(row["image_digest"]),
        asset_manifest_digest=str(row["asset_manifest_digest"]),
        semantic_profile_digest=str(row["semantic_profile_digest"]),
        previously_enabled=cast(bool, row["previously_enabled"]),
        revision=cast(int, row["revision"]),
        effective_at=cast(datetime, row["effective_at"]),
        ontology_release_id=str(row["ontology_release_id"]),
        ontology_release_digest=str(row["ontology_release_digest"]),
        source_authority=str(row["source_authority"]),
    )


def _cursor(row: dict[str, Any]) -> CostCollectionCursor:
    return CostCollectionCursor(
        package_id=str(row["package_id"]),
        scope_id=str(row["scope_id"]),
        revision=cast(int, row["revision"]),
        resume_token=str(row["resume_token"]) if row["resume_token"] is not None else None,
        coverage_through_at=cast(datetime, row["coverage_through_at"]),
        retention_floor_at=cast(datetime, row["retention_floor_at"]),
        analysis_revision=cast(int, row["analysis_revision"]),
        last_published_at=cast(datetime | None, row["last_published_at"]),
        last_published_observation_id=(
            str(row["last_published_observation_id"])
            if row["last_published_observation_id"] is not None
            else None
        ),
    )


def _observation_values(item: CostObservation) -> tuple[object, ...]:
    return (
        item.observation_id,
        item.package_id,
        item.scope_id,
        item.service_id,
        item.amount,
        item.currency,
        item.event_start_at,
        item.event_end_at,
        item.observed_at,
        item.recorded_at,
        item.source_authority,
        item.source_uri,
        item.completeness,
        item.ontology_release_id,
        item.ontology_release_digest,
        item.evidence_digest,
        item.retention_until,
    )


def _current_observation_values(item: CostObservation) -> tuple[object, ...]:
    return (
        item.package_id,
        item.scope_id,
        item.service_id,
        item.currency,
        item.event_start_at.astimezone(UTC).date(),
        item.observation_id,
        item.recorded_at,
    )


def _observation(row: dict[str, Any]) -> CostObservation:
    return CostObservation(
        observation_id=str(row["observation_id"]),
        package_id=str(row["package_id"]),
        scope_id=str(row["scope_id"]),
        service_id=str(row["service_id"]),
        amount=cast(Decimal, row["amount"]),
        currency=str(row["currency"]),
        event_start_at=cast(datetime, row["event_start_at"]),
        event_end_at=cast(datetime, row["event_end_at"]),
        observed_at=cast(datetime, row["observed_at"]),
        recorded_at=cast(datetime, row["recorded_at"]),
        source_authority=str(row["source_authority"]),
        source_uri=str(row["source_uri"]),
        completeness=cast(Decimal, row["completeness"]),
        ontology_release_id=str(row["ontology_release_id"]),
        ontology_release_digest=str(row["ontology_release_digest"]),
        evidence_digest=str(row["evidence_digest"]),
        retention_until=cast(datetime, row["retention_until"]),
    )


__all__ = ["PostgresCostGovernanceConfig", "PostgresCostGovernanceStore"]
