"""PostgreSQL persistence for Cost Governance activation and evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

import psycopg
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
                SELECT observation_id, package_id, scope_id, service_id, amount,
                       currency, event_start_at, event_end_at, observed_at,
                       recorded_at, source_authority, source_uri, completeness,
                       ontology_release_id, ontology_release_digest, evidence_digest,
                       retention_until
                  FROM cost_observation
                 WHERE package_id = %s AND scope_id = %s AND observed_at >= %s
                 ORDER BY observed_at, observation_id
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
