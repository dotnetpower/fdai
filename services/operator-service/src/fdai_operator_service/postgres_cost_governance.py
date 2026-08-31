"""Operator-owned reads for Cost Governance activation, access, and projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from fdai_service_contracts import (
    CostAccessGrant,
    CostAnalyticsProjection,
    CostDisclosureCeiling,
    CostDisclosurePolicy,
    CostGovernanceUnavailableReason,
    CostProjectionRecord,
)
from psycopg.rows import dict_row

from fdai_operator_service.families.cost_governance import (
    CostAccessDecision,
    CostActivationSnapshot,
)


@dataclass(frozen=True, slots=True)
class PostgresCostGovernanceConfig:
    """Bounded connection configuration for read-only package projections."""

    dsn: str
    statement_timeout_ms: int = 5_000
    connect_timeout_s: int = 5


class PostgresCostGovernanceReader:
    """Read Cost Governance state without provider or mutation authority."""

    def __init__(self, config: PostgresCostGovernanceConfig) -> None:
        self._config = config

    async def read_access(
        self,
        *,
        principal_id: str,
        purpose: str,
        scope: str,
        now: datetime,
    ) -> CostAccessDecision:
        rows = await self._fetch(
            """
            SELECT access_grant.grant_id, access_grant.principal_id,
                   access_grant.revision, access_grant.purpose,
                   access_grant.scopes, access_grant.disclosure,
                   access_grant.effective_at, access_grant.expires_at,
                   access_grant.source_authority, ceiling.disclosure AS ceiling_disclosure,
                   ceiling.revision AS ceiling_revision,
                   ceiling.effective_at AS ceiling_effective_at,
                   ceiling.source_authority AS ceiling_source_authority
            FROM cost_access_grant AS access_grant
            LEFT JOIN LATERAL (
                SELECT revision, disclosure, effective_at, source_authority
                FROM cost_disclosure_ceiling
                WHERE singleton = TRUE AND effective_at <= %(now)s
                ORDER BY revision DESC
                LIMIT 1
            ) AS ceiling ON TRUE
            WHERE access_grant.principal_id = %(principal_id)s
              AND access_grant.purpose = %(purpose)s
              AND access_grant.scopes ? %(scope)s
            ORDER BY access_grant.revision DESC
            LIMIT 1
            """,
            {"principal_id": principal_id, "purpose": purpose, "scope": scope, "now": now},
        )
        if not rows:
            return CostAccessDecision(
                grant=None,
                ceiling=None,
                reason=CostGovernanceUnavailableReason.ACCESS_GRANT_MISSING,
            )
        row = rows[0]
        if row["expires_at"] <= now or row["effective_at"] > now:
            return CostAccessDecision(
                grant=None,
                ceiling=None,
                reason=CostGovernanceUnavailableReason.ACCESS_GRANT_EXPIRED,
            )
        ceiling = row.get("ceiling_disclosure")
        if (
            not isinstance(ceiling, Mapping)
            or row.get("ceiling_revision") is None
            or row.get("ceiling_effective_at") is None
            or row.get("ceiling_source_authority") is None
        ):
            return CostAccessDecision(
                grant=None,
                ceiling=None,
                reason=CostGovernanceUnavailableReason.SOURCE_UNAVAILABLE,
            )
        return CostAccessDecision(
            grant=CostAccessGrant(
                grant_id=str(row["grant_id"]),
                principal_id=str(row["principal_id"]),
                revision=int(row["revision"]),
                purpose=str(row["purpose"]),
                scopes=tuple(str(value) for value in row["scopes"]),
                disclosure=CostDisclosurePolicy.model_validate(row["disclosure"]),
                effective_at=row["effective_at"],
                expires_at=row["expires_at"],
                source_authority=str(row["source_authority"]),
            ),
            ceiling=CostDisclosureCeiling(
                revision=int(row["ceiling_revision"]),
                disclosure=CostDisclosurePolicy.model_validate(ceiling),
                effective_at=row["ceiling_effective_at"],
                source_authority=str(row["ceiling_source_authority"]),
            ),
        )

    async def read_activation(self, package_id: str) -> CostActivationSnapshot | None:
        rows = await self._fetch(
            """
            SELECT vertical_id, package_id, available, enabled, availability_reasons,
                   package_version, image_digest, asset_manifest_digest,
                   semantic_profile_digest, ontology_release_digest, revision
            FROM vertical_package_activation
            WHERE package_id = %(package_id)s
            """,
            {"package_id": package_id},
        )
        if not rows:
            return None
        row = rows[0]
        return CostActivationSnapshot(
            vertical_id=str(row["vertical_id"]),
            package_id=str(row["package_id"]),
            available=bool(row["available"]),
            enabled=bool(row["enabled"]),
            availability_reasons=tuple(str(value) for value in row["availability_reasons"]),
            package_version=str(row["package_version"]),
            image_digest=str(row["image_digest"]),
            asset_manifest_digest=str(row["asset_manifest_digest"]),
            semantic_profile_digest=str(row["semantic_profile_digest"]),
            ontology_release_digest=str(row["ontology_release_digest"]),
            revision=int(row["revision"]),
        )

    async def read_analytics(self, *, scope: str) -> CostAnalyticsProjection | None:
        """Read the latest immutable analytics snapshot without raw identifiers."""

        query = (
            """
            SELECT payload
              FROM cost_governance_analytics_snapshot
             WHERE scope_id = (
                SELECT MIN(candidate.scope_id)
                  FROM (
                    SELECT analytics_scope.scope_id
                      FROM (
                        SELECT DISTINCT scope_id
                          FROM cost_governance_analytics_snapshot
                      ) AS analytics_scope
                      JOIN (
                        SELECT DISTINCT scope_id
                          FROM cost_observation
                      ) AS observation_scope
                        ON observation_scope.scope_id = analytics_scope.scope_id
                  ) AS candidate
                HAVING COUNT(DISTINCT candidate.scope_id) = 1
                   AND (
                        SELECT COUNT(DISTINCT scope_id)
                          FROM cost_governance_analytics_snapshot
                   ) = 1
                   AND (
                        SELECT COUNT(DISTINCT scope_id)
                          FROM cost_observation
                   ) = 1
            )
            ORDER BY observed_at DESC, snapshot_id DESC
            LIMIT 1
            """
            if scope == "*"
            else """
            SELECT payload
             FROM cost_governance_analytics_snapshot
            WHERE scope_id = %(scope)s
            ORDER BY observed_at DESC, snapshot_id DESC
            LIMIT 1
            """
        )
        rows = await self._fetch(
            query,
            {"scope": scope},
        )
        if not rows:
            return None
        return CostAnalyticsProjection.model_validate(rows[0]["payload"])

    async def set_enabled(
        self,
        *,
        package_id: str,
        actor_id: str,
        enabled: bool,
        expected_revision: int,
        request_id: str,
    ) -> CostActivationSnapshot:
        """Apply the database-owned audited activation transition."""

        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                connect_timeout=self._config.connect_timeout_s,
                row_factory=dict_row,
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                cursor = await connection.execute(
                    """
                    SELECT *
                      FROM fdai_set_cost_governance_enabled(
                          %(package_id)s,
                          %(actor_id)s,
                          %(enabled)s,
                          %(expected_revision)s,
                          %(request_id)s
                      )
                    """,
                    {
                        "package_id": package_id,
                        "actor_id": actor_id,
                        "enabled": enabled,
                        "expected_revision": expected_revision,
                        "request_id": request_id,
                    },
                )
                row = await cursor.fetchone()
        except psycopg.Error as exc:
            message = exc.diag.message_primary or ""
            if exc.sqlstate in {"CG001", "CG002", "CG003"}:
                raise ValueError(message or "Cost Governance activation conflict") from exc
            raise RuntimeError("Cost Governance activation persistence is unavailable") from exc
        if row is None:
            raise RuntimeError("Cost Governance activation returned no state")
        return CostActivationSnapshot(
            vertical_id=str(row["vertical_id"]),
            package_id=str(row["package_id"]),
            available=bool(row["available"]),
            enabled=bool(row["enabled"]),
            availability_reasons=tuple(str(value) for value in row["availability_reasons"]),
            package_version=str(row["package_version"]),
            image_digest=str(row["image_digest"]),
            asset_manifest_digest=str(row["asset_manifest_digest"]),
            semantic_profile_digest=str(row["semantic_profile_digest"]),
            ontology_release_digest=str(row["ontology_release_digest"]),
            revision=int(row["revision"]),
        )

    async def read_records(
        self,
        *,
        surface: str,
        scope: str,
        limit: int,
    ) -> tuple[CostProjectionRecord, ...]:
        rows = await self._fetch(
            """
            SELECT observation_id, scope_id, service_id, amount, currency,
                   observed_at, completeness, source_authority, evidence_digest
            FROM cost_observation
            WHERE (%(scope)s = '*' OR scope_id = %(scope)s)
            ORDER BY observed_at DESC, observation_id
            LIMIT %(limit)s
            """,
            {"scope": scope, "limit": limit},
        )
        return tuple(
            CostProjectionRecord(
                record_id=str(row["observation_id"]),
                group_id=str(row["service_id"]),
                resource_id=str(row["scope_id"]),
                service_id=str(row["service_id"]),
                amount=Decimal(str(row["amount"])),
                currency=str(row["currency"]),
                observed_at=row["observed_at"],
                completeness=Decimal(str(row["completeness"])),
                source_authority=str(row["source_authority"]),
                provenance_digest=str(row["evidence_digest"]),
                status=f"{surface}.observed",
            )
            for row in rows
        )

    async def _fetch(
        self,
        query: str,
        params: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            _psycopg_dsn(self._config.dsn),
            connect_timeout=self._config.connect_timeout_s,
            row_factory=dict_row,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(query, dict(params))
            return [dict(row) for row in await cursor.fetchall()]


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


class UnavailableCostGovernanceReader:
    """Fail-closed family dependencies when PostgreSQL is not configured."""

    async def read_access(
        self,
        *,
        principal_id: str,
        purpose: str,
        scope: str,
        now: datetime,
    ) -> CostAccessDecision:
        del principal_id, purpose, scope, now
        return CostAccessDecision(
            grant=None,
            ceiling=None,
            reason=CostGovernanceUnavailableReason.SOURCE_UNAVAILABLE,
        )

    async def read_activation(self, package_id: str) -> CostActivationSnapshot | None:
        del package_id
        return None

    async def read_records(
        self,
        *,
        surface: str,
        scope: str,
        limit: int,
    ) -> tuple[CostProjectionRecord, ...]:
        del surface, scope, limit
        return ()


__all__ = [
    "PostgresCostGovernanceConfig",
    "PostgresCostGovernanceReader",
    "UnavailableCostGovernanceReader",
]
