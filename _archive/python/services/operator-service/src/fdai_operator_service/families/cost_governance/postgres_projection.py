"""PostgreSQL reads for explicit Cost Governance evidence and lineage."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from hashlib import sha256
from typing import Any

from fdai_operator_service.families.cost_governance.contracts import (
    CostProjectionEvidenceSnapshot,
)
from fdai_service_contracts import (
    CostAnalyticsRunReceipt,
    CostDecisionCaseProjection,
    CostEvidenceSourceFacet,
    CostEvidenceState,
    CostSettlementEffectProjection,
    CostSettlementOutcomeProjection,
)

FetchRows = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]


async def read_projection_evidence(
    fetch: FetchRows,
    *,
    scope: str,
    analytics_snapshot_id: str | None,
) -> CostProjectionEvidenceSnapshot:
    """Read bounded evidence metadata without returning observation content."""

    params: Mapping[str, object] = {
        "scope": scope,
        "analytics_snapshot_id": analytics_snapshot_id,
    }
    rows = await fetch(
        """
        SELECT
          MIN(event_start_at) AS window_start_at,
          MAX(event_end_at) AS window_end_at,
          MAX(observed_at) AS latest_source_at,
          COUNT(*) FILTER (WHERE completeness = 1) AS complete_count,
          COUNT(*) FILTER (WHERE completeness < 1) AS partial_count,
          (
            SELECT COUNT(*)
              FROM cost_governance_case_projection AS candidate
              JOIN cost_governance_episode AS episode
                ON episode.episode_id = candidate.episode_id
               AND episode.revision = candidate.episode_revision
              JOIN cost_governance_retention AS retention
                ON retention.episode_id = episode.episode_id
             WHERE (%(scope)s = '*' OR candidate.scope_id = %(scope)s)
               AND episode.observation_mode
               AND episode.outcome = 'hold'
               AND retention.purged_at IS NULL
          ) AS decision_case_count,
          (
            SELECT COUNT(*)
              FROM cost_governance_episode AS episode
              JOIN cost_governance_retention AS retention
                ON retention.episode_id = episode.episode_id
             WHERE episode.observation_mode
               AND episode.outcome = 'hold'
               AND retention.purged_at IS NULL
               AND (
                    %(scope)s = '*'
                    OR EXISTS (
                        SELECT 1
                          FROM cost_governance_case_projection AS scoped_candidate
                         WHERE scoped_candidate.episode_id = episode.episode_id
                           AND scoped_candidate.episode_revision = episode.revision
                           AND scoped_candidate.scope_id = %(scope)s
                    )
               )
               AND NOT EXISTS (
                    SELECT 1
                      FROM cost_governance_case_projection AS candidate
                     WHERE candidate.episode_id = episode.episode_id
                       AND candidate.episode_revision = episode.revision
                       AND (%(scope)s = '*' OR candidate.scope_id = %(scope)s)
                       AND EXISTS (
                        SELECT 1 FROM cost_governance_evidence AS evidence
                         WHERE evidence.episode_id = candidate.episode_id
                           AND evidence.episode_revision = candidate.episode_revision
                    )
               )
          ) AS incomplete_decision_case_count,
          (
            SELECT COUNT(*)
              FROM cost_governance_settlement AS settlement
              JOIN cost_governance_case_projection AS candidate
                ON candidate.episode_id = settlement.episode_id
               AND candidate.episode_revision = settlement.episode_revision
              JOIN cost_governance_retention AS retention
                ON retention.episode_id = settlement.episode_id
             WHERE (%(scope)s = '*' OR candidate.scope_id = %(scope)s)
               AND retention.purged_at IS NULL
               AND settlement.action_ref IS NOT NULL
               AND settlement.action_revision IS NOT NULL
          ) AS settlement_count,
          (
            SELECT COUNT(*)
              FROM cost_governance_settlement AS settlement
              JOIN cost_governance_case_projection AS candidate
                ON candidate.episode_id = settlement.episode_id
               AND candidate.episode_revision = settlement.episode_revision
              JOIN cost_governance_retention AS retention
                ON retention.episode_id = settlement.episode_id
             WHERE (%(scope)s = '*' OR candidate.scope_id = %(scope)s)
               AND retention.purged_at IS NULL
               AND (
                    NOT settlement.terminal
                    OR settlement.rollback_request_id IS NOT NULL
                    OR settlement.action_ref IS NULL
                    OR settlement.action_revision IS NULL
                    OR (
                        settlement.realized_savings > 0
                        AND settlement.currency IS NULL
                    )
                    OR EXISTS (
                        SELECT 1 FROM cost_governance_effect_settlement AS effect
                         WHERE effect.episode_id = settlement.episode_id
                           AND effect.episode_revision = settlement.episode_revision
                           AND (NOT effect.terminal OR effect.status <> 'verified')
                    )
               )
          ) AS incomplete_settlement_count
        FROM cost_observation_current AS current
        JOIN cost_observation AS observation
          ON observation.observation_id = current.observation_id
        WHERE (%(scope)s = '*' OR current.scope_id = %(scope)s)
        """,
        params,
    )
    row = rows[0] if rows else {}
    source_rows = await fetch(
        """
        SELECT source_authority, MIN(event_start_at) AS window_start_at,
               MAX(event_end_at) AS window_end_at,
               MAX(observed_at) AS latest_source_at,
               COUNT(*) FILTER (WHERE completeness = 1) AS complete_count,
               COUNT(*) FILTER (WHERE completeness < 1) AS partial_count
          FROM cost_observation_current AS current
          JOIN cost_observation AS observation
            ON observation.observation_id = current.observation_id
         WHERE (%(scope)s = '*' OR current.scope_id = %(scope)s)
         GROUP BY observation.source_authority
         ORDER BY observation.source_authority
        """,
        params,
    )
    sources = tuple(
        CostEvidenceSourceFacet(
            source_authority=str(item["source_authority"]),
            state=(
                CostEvidenceState.PARTIAL
                if int(item["partial_count"] or 0)
                else CostEvidenceState.COMPLETE
            ),
            window_start_at=item["window_start_at"],
            window_end_at=item["window_end_at"],
            latest_source_at=item["latest_source_at"],
            complete_count=int(item["complete_count"] or 0),
            partial_count=int(item["partial_count"] or 0),
            reason="source_partial" if int(item["partial_count"] or 0) else None,
        )
        for item in source_rows
    )
    run_rows = await fetch(
        """
        SELECT run_id, receipt_digest, scope_digest, venue, window_start_at,
               window_end_at, started_at, finished_at, status, sources,
               observation_count, trend_point_count, budget_count,
               recommendation_count, utilization_count, limitations,
               failure_reason, snapshot_id
          FROM cost_governance_analytics_run_receipt
         WHERE %(scope)s <> '*'
           AND scope_id = %(scope)s
         ORDER BY finished_at DESC, run_id DESC
         LIMIT 1
        """,
        params,
    )
    latest_run = CostAnalyticsRunReceipt.model_validate(run_rows[0]) if run_rows else None
    return CostProjectionEvidenceSnapshot(
        window_start_at=row.get("window_start_at"),
        window_end_at=row.get("window_end_at"),
        latest_source_at=row.get("latest_source_at"),
        complete_count=int(row.get("complete_count") or 0),
        partial_count=int(row.get("partial_count") or 0),
        sources=sources,
        latest_analytics_run=latest_run,
        resource_candidate_count=0,
        incomplete_candidate_count=0,
        decision_case_count=int(row.get("decision_case_count") or 0),
        incomplete_decision_case_count=int(row.get("incomplete_decision_case_count") or 0),
        settlement_count=int(row.get("settlement_count") or 0),
        incomplete_settlement_count=int(row.get("incomplete_settlement_count") or 0),
    )


async def read_decision_cases(
    fetch: FetchRows,
    *,
    scope: str,
    limit: int,
    pseudonym_key: bytes,
) -> tuple[CostDecisionCaseProjection, ...]:
    """Read only complete explicit observation-mode case snapshots."""

    rows = await fetch(
        """
        SELECT candidate.episode_id, candidate.episode_revision,
               candidate.evidence_cutoff, candidate.decision_frame_digest,
               candidate.target_refs, candidate.options,
               candidate.selected_option_id, candidate.verdict, candidate.reason,
               candidate.recorded_at, candidate.source_authority,
               ARRAY(
                   SELECT evidence.evidence_ref
                     FROM cost_governance_evidence AS evidence
                    WHERE evidence.episode_id = candidate.episode_id
                      AND evidence.episode_revision = candidate.episode_revision
                    ORDER BY evidence.evidence_sequence
               ) AS evidence_refs,
               ARRAY(
                   SELECT DISTINCT evidence.source_authority
                     FROM cost_governance_evidence AS evidence
                    WHERE evidence.episode_id = candidate.episode_id
                      AND evidence.episode_revision = candidate.episode_revision
                    ORDER BY evidence.source_authority
               ) AS evidence_sources,
               ARRAY(
                   SELECT recovery.step || ':' || recovery.status
                     FROM cost_governance_recovery AS recovery
                    WHERE recovery.episode_id = candidate.episode_id
                      AND recovery.episode_revision = candidate.episode_revision
                    ORDER BY recovery.attempt_index
               ) AS recovery_steps
          FROM cost_governance_case_projection AS candidate
          JOIN cost_governance_episode AS episode
            ON episode.episode_id = candidate.episode_id
           AND episode.revision = candidate.episode_revision
          JOIN cost_governance_retention AS retention
            ON retention.episode_id = episode.episode_id
         WHERE (%(scope)s = '*' OR candidate.scope_id = %(scope)s)
           AND episode.observation_mode
           AND episode.outcome = 'hold'
           AND retention.purged_at IS NULL
           AND EXISTS (
               SELECT 1 FROM cost_governance_evidence AS evidence
                WHERE evidence.episode_id = candidate.episode_id
                  AND evidence.episode_revision = candidate.episode_revision
           )
         ORDER BY candidate.recorded_at DESC, candidate.episode_id
         LIMIT %(limit)s
        """,
        {"scope": scope, "limit": limit},
    )
    projected: list[CostDecisionCaseProjection] = []
    for row in rows:
        raw_options = row.get("options")
        options: list[Any] = raw_options if isinstance(raw_options, list) else []
        option_ids = tuple(
            str(item.get("option_id"))
            for item in options
            if isinstance(item, Mapping) and isinstance(item.get("option_id"), str)
        )
        raw_targets = row.get("target_refs")
        targets: list[Any] = raw_targets if isinstance(raw_targets, list) else []
        if not option_ids or not targets:
            continue
        projected.append(
            CostDecisionCaseProjection(
                case_ref=_pseudonym("case", str(row["episode_id"]), pseudonym_key),
                revision=int(row["episode_revision"]),
                target_refs=tuple(
                    _pseudonym("resource", str(target), pseudonym_key) for target in targets
                ),
                evidence_cutoff=row["evidence_cutoff"],
                decision_frame_digest=str(row["decision_frame_digest"]),
                option_ids=option_ids,
                selected_option_id=(
                    str(row["selected_option_id"])
                    if row.get("selected_option_id") is not None
                    else None
                ),
                verdict="hold",
                reason=str(row["reason"]),
                evidence_refs=tuple(str(item) for item in row["evidence_refs"]),
                evidence_sources=tuple(str(item) for item in row["evidence_sources"]),
                recovery_steps=tuple(str(item) for item in row["recovery_steps"]),
                recorded_at=row["recorded_at"],
                source_authority=str(row["source_authority"]),
            )
        )
    return tuple(projected)


async def read_settlement_outcomes(
    fetch: FetchRows,
    *,
    scope: str,
    limit: int,
    pseudonym_key: bytes,
) -> tuple[CostSettlementOutcomeProjection, ...]:
    """Read persisted settlement rows without deriving outcomes from observations."""

    rows = await fetch(
        """
        SELECT candidate.episode_id, candidate.episode_revision,
               candidate.decision_frame_digest, settlement.terminal,
               settlement.realized_savings, settlement.currency,
               settlement.action_ref, settlement.action_revision,
               settlement.rollback_request_id,
               settlement.recovery_observed, settlement.settled_at,
               COALESCE(
                   jsonb_agg(
                       jsonb_build_object(
                           'effect_id', effect.effect_id,
                           'kind', effect.effect_kind,
                           'status', effect.status,
                           'reason', effect.reason,
                           'terminal', effect.terminal,
                           'observation_digest', effect.observation_digest,
                           'completeness_digest', effect.completeness_digest
                       ) ORDER BY effect.effect_id
                   ) FILTER (WHERE effect.effect_id IS NOT NULL),
                   '[]'::jsonb
               ) AS effects
          FROM cost_governance_case_projection AS candidate
          JOIN cost_governance_episode AS episode
            ON episode.episode_id = candidate.episode_id
           AND episode.revision = candidate.episode_revision
          JOIN cost_governance_retention AS retention
            ON retention.episode_id = episode.episode_id
          JOIN cost_governance_settlement AS settlement
            ON settlement.episode_id = candidate.episode_id
           AND settlement.episode_revision = candidate.episode_revision
          LEFT JOIN cost_governance_effect_settlement AS effect
            ON effect.episode_id = settlement.episode_id
           AND effect.episode_revision = settlement.episode_revision
         WHERE (%(scope)s = '*' OR candidate.scope_id = %(scope)s)
           AND episode.observation_mode
           AND episode.outcome = 'hold'
           AND retention.purged_at IS NULL
           AND settlement.action_ref IS NOT NULL
           AND settlement.action_revision IS NOT NULL
         GROUP BY candidate.episode_id, candidate.episode_revision,
                  candidate.decision_frame_digest, settlement.terminal,
                  settlement.realized_savings, settlement.currency,
                  settlement.action_ref, settlement.action_revision,
                  settlement.rollback_request_id,
                  settlement.recovery_observed, settlement.settled_at
         ORDER BY settlement.settled_at DESC, candidate.episode_id
         LIMIT %(limit)s
        """,
        {"scope": scope, "limit": limit},
    )
    projected: list[CostSettlementOutcomeProjection] = []
    for row in rows:
        action_ref = row.get("action_ref")
        action_revision = row.get("action_revision")
        if (
            not isinstance(action_ref, str)
            or not isinstance(action_revision, int)
            or isinstance(action_revision, bool)
        ):
            continue
        effects = tuple(
            CostSettlementEffectProjection.model_validate(item)
            for item in (row.get("effects") or [])
        )
        if not effects:
            continue
        verified = (
            bool(row["terminal"])
            and row.get("rollback_request_id") is None
            and all(item.terminal and item.status == "verified" for item in effects)
        )
        projected.append(
            CostSettlementOutcomeProjection(
                case_ref=_pseudonym("case", str(row["episode_id"]), pseudonym_key),
                revision=int(row["episode_revision"]),
                action_ref=action_ref,
                action_revision=action_revision,
                decision_frame_digest=str(row["decision_frame_digest"]),
                terminal=bool(row["terminal"]),
                verified_savings=(
                    Decimal(str(row["realized_savings"]))
                    if verified and row.get("currency") is not None
                    else None
                ),
                currency=str(row["currency"]) if verified and row.get("currency") else None,
                rollback_requested=row.get("rollback_request_id") is not None,
                recovery_observed=bool(row["recovery_observed"]),
                effects=effects,
                settled_at=row["settled_at"],
            )
        )
    return tuple(projected)


def _pseudonym(prefix: str, value: str, key: bytes) -> str:
    digest = hmac.new(key, f"{prefix}:{value}".encode(), sha256).hexdigest()[:24]
    return f"{prefix}:{digest}"


__all__ = [
    "read_decision_cases",
    "read_projection_evidence",
    "read_settlement_outcomes",
]
