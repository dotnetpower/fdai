"""Compose disclosure-safe Cost Governance items and evidence readiness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal

from fdai_operator_service.families.cost_governance.contracts import (
    CostProjectionEvidenceSnapshot,
)
from fdai_service_contracts import (
    CostAnalyticsProjection,
    CostDecisionCaseProjection,
    CostDisclosurePolicy,
    CostEvidenceFreshness,
    CostEvidenceSourceFacet,
    CostEvidenceState,
    CostGovernanceItem,
    CostGranularity,
    CostIdentityVisibility,
    CostProjectionEvidence,
    CostProjectionRecord,
    CostReadinessReason,
    CostResourceCandidateProjection,
    CostResourceEfficiencyProjection,
    CostSettlementOutcomeProjection,
    CostSummaryProjection,
    CostSurfaceReadiness,
    CostTrendProjection,
    disclose_cost_records,
)

FRESHNESS_THRESHOLD = timedelta(days=2)
ResourceEfficiencyMode = Literal["service_summary", "resource_candidate"]


def projection_items(
    *,
    surface: str,
    records: Sequence[CostProjectionRecord],
    disclosure: CostDisclosurePolicy,
    candidates: tuple[CostResourceCandidateProjection, ...],
    cases: tuple[CostDecisionCaseProjection, ...],
    outcomes: tuple[CostSettlementOutcomeProjection, ...],
    pseudonym_key: bytes | None,
) -> tuple[tuple[CostGovernanceItem, ...], ResourceEfficiencyMode | None]:
    """Select one truthful item mode for the requested surface."""

    if surface == "optimization-cases":
        return cases, None
    if surface == "outcomes":
        return outcomes, None
    if surface == "resource-efficiency" and candidates:
        return candidates, "resource_candidate"
    effective = disclosure
    mode: ResourceEfficiencyMode | None = None
    if surface == "resource-efficiency":
        effective = disclosure.model_copy(
            update={
                "granularity": CostGranularity.GROUP,
                "identity_visibility": CostIdentityVisibility.NONE,
            }
        )
        mode = "service_summary"
    disclosed = disclose_cost_records(records, effective, pseudonym_key=pseudonym_key)
    return _typed_items(surface, disclosed), mode


def resource_candidates(
    analytics: CostAnalyticsProjection | None,
    disclosure: CostDisclosurePolicy,
    *,
    pseudonym_key: bytes | None,
) -> tuple[CostResourceCandidateProjection, ...]:
    """Project only candidates with complete pseudonymous sizing evidence."""

    if (
        analytics is None
        or disclosure.granularity is not CostGranularity.RESOURCE
        or disclosure.identity_visibility is CostIdentityVisibility.NONE
        or pseudonym_key is None
    ):
        return ()
    return tuple(
        CostResourceCandidateProjection(
            recommendation_ref=item.recommendation_ref,
            resource=item.resource_ref,
            resource_type=item.resource_type,
            current_configuration=item.current_sku,
            proposed_configuration=item.target_sku,
            utilization_metric=item.utilization_metric,
            utilization_percent=item.utilization_percent,
            projected_monthly_savings=item.monthly_savings,
            currency=item.currency,
            observed_at=item.observed_at,
            source_authority=item.source_authority,
        )
        for item in analytics.recommendations
        if item.resource_ref is not None
        and item.current_sku is not None
        and item.target_sku is not None
        and item.utilization_metric is not None
        and item.utilization_percent is not None
    )


def projection_evidence(
    *,
    snapshot: CostProjectionEvidenceSnapshot,
    disclosure: CostDisclosurePolicy,
    analytics: CostAnalyticsProjection | None,
    analytics_snapshot_id: str | None,
    candidates: tuple[CostResourceCandidateProjection, ...],
    can_disclose_lineage: bool,
    requested_surface: str,
    observation_returned_count: int | None,
    candidate_returned_count: int,
    case_returned_count: int,
    settlement_returned_count: int,
    now: datetime,
) -> CostProjectionEvidence:
    """Compute freshness and independent facet readiness from persisted evidence."""

    analytics_latest = analytics.observed_at if analytics else None
    latest_values = tuple(
        value for value in (snapshot.latest_source_at, analytics_latest) if value is not None
    )
    latest = max(latest_values) if latest_values else None
    freshness = _freshness(latest, now)
    observation_state, observation_reason = _observation_readiness(
        snapshot,
        _freshness(snapshot.latest_source_at, now),
        truncated=(
            observation_returned_count is not None
            and observation_returned_count < snapshot.complete_count + snapshot.partial_count
        ),
    )
    analytics_state, analytics_reason = _analytics_readiness(
        snapshot,
        analytics=analytics,
        analytics_snapshot_id=analytics_snapshot_id,
        now=now,
    )
    candidate_total = len(analytics.recommendations) if analytics is not None else 0
    candidate_incomplete = max(0, candidate_total - len(candidates))
    candidate_truncated = requested_surface == "resource-efficiency" and (
        "advisor_recommendation_limit" in (analytics.limitations if analytics else ())
        or (
            snapshot.resource_candidate_count > 0
            and candidate_returned_count < snapshot.resource_candidate_count
        )
    )
    if candidate_truncated:
        candidate_state = CostEvidenceState.PARTIAL
        candidate_reason = CostReadinessReason.PROJECTION_TRUNCATED
    elif not can_disclose_lineage:
        candidate_state = CostEvidenceState.UNAVAILABLE
        candidate_reason = CostReadinessReason.DISCLOSURE_INSUFFICIENT
    elif analytics_state is not CostEvidenceState.COMPLETE:
        candidate_state = analytics_state
        candidate_reason = CostReadinessReason.CANDIDATE_EVIDENCE_INCOMPLETE
    elif candidates and not candidate_incomplete:
        candidate_state, candidate_reason = CostEvidenceState.COMPLETE, None
    elif candidates:
        candidate_state = CostEvidenceState.PARTIAL
        candidate_reason = CostReadinessReason.CANDIDATE_EVIDENCE_INCOMPLETE
    else:
        candidate_state = CostEvidenceState.UNAVAILABLE
        candidate_reason = CostReadinessReason.RESOURCE_CANDIDATES_MISSING
    case_state, case_reason = _count_readiness(
        count=snapshot.decision_case_count,
        incomplete=snapshot.incomplete_decision_case_count,
        missing=CostReadinessReason.DECISION_CASES_MISSING,
        partial=CostReadinessReason.DECISION_CASE_INCOMPLETE,
        disclosure_allowed=can_disclose_lineage,
        truncated=(
            requested_surface == "optimization-cases"
            and case_returned_count
            < max(
                0,
                snapshot.decision_case_count - snapshot.incomplete_decision_case_count,
            )
        ),
    )
    settlement_state, settlement_reason = _count_readiness(
        count=snapshot.settlement_count,
        incomplete=snapshot.incomplete_settlement_count,
        missing=CostReadinessReason.SETTLEMENTS_MISSING,
        partial=CostReadinessReason.SETTLEMENT_INCOMPLETE,
        disclosure_allowed=can_disclose_lineage,
        truncated=(
            requested_surface == "outcomes"
            and settlement_returned_count < snapshot.settlement_count
        ),
    )
    readiness = (
        CostSurfaceReadiness(
            surface="observations",
            state=observation_state,
            reason=observation_reason,
            record_count=snapshot.complete_count + snapshot.partial_count,
            returned_count=(
                snapshot.complete_count + snapshot.partial_count
                if observation_returned_count is None
                else observation_returned_count
            ),
            truncated=observation_reason is CostReadinessReason.PROJECTION_TRUNCATED,
            latest_evidence_at=snapshot.latest_source_at,
        ),
        CostSurfaceReadiness(
            surface="analytics",
            state=analytics_state,
            reason=analytics_reason,
            record_count=(
                1 if snapshot.latest_analytics_run is not None or analytics is not None else 0
            ),
            returned_count=1 if analytics is not None else 0,
            latest_evidence_at=(
                snapshot.latest_analytics_run.finished_at
                if snapshot.latest_analytics_run is not None
                else None
            ),
        ),
        CostSurfaceReadiness(
            surface="resource-candidates",
            state=candidate_state,
            reason=candidate_reason,
            record_count=max(snapshot.resource_candidate_count, candidate_total),
            returned_count=candidate_returned_count,
            truncated=candidate_truncated,
            latest_evidence_at=analytics.observed_at if analytics is not None else None,
        ),
        CostSurfaceReadiness(
            surface="decision-cases",
            state=case_state,
            reason=case_reason,
            record_count=snapshot.decision_case_count,
            returned_count=case_returned_count,
            truncated=case_reason is CostReadinessReason.PROJECTION_TRUNCATED,
        ),
        CostSurfaceReadiness(
            surface="settlements",
            state=settlement_state,
            reason=settlement_reason,
            record_count=snapshot.settlement_count,
            returned_count=settlement_returned_count,
            truncated=settlement_reason is CostReadinessReason.PROJECTION_TRUNCATED,
        ),
    )
    sources = _merge_sources(
        snapshot.sources,
        (
            *(analytics.sources if analytics else ()),
            *(
                snapshot.latest_analytics_run.sources
                if snapshot.latest_analytics_run is not None
                else ()
            ),
        ),
    )
    return CostProjectionEvidence(
        window_start_at=_minimum_time(
            snapshot.window_start_at,
            analytics.window_start_at if analytics else None,
        ),
        window_end_at=_maximum_time(
            snapshot.window_end_at,
            analytics.window_end_at if analytics else None,
        ),
        latest_source_at=latest,
        freshness=freshness,
        freshness_threshold_seconds=int(FRESHNESS_THRESHOLD.total_seconds()),
        complete_count=snapshot.complete_count,
        partial_count=snapshot.partial_count,
        sources=sources,
        disclosure=disclosure,
        readiness=readiness,
        latest_analytics_run=snapshot.latest_analytics_run,
    )


def surface_complete(
    surface: str,
    evidence: CostProjectionEvidence,
    *,
    resource_efficiency_mode: ResourceEfficiencyMode | None,
) -> bool:
    """Return whether the evidence required by one route is complete."""

    states: Mapping[str, CostEvidenceState] = {
        item.surface: item.state for item in evidence.readiness
    }
    required_by_surface: Mapping[str, tuple[str, ...]] = {
        "overview": ("observations", "analytics"),
        "resource-efficiency": (
            ("resource-candidates",)
            if resource_efficiency_mode == "resource_candidate"
            else ("observations",)
        ),
        "optimization-cases": ("decision-cases",),
        "outcomes": ("settlements",),
    }
    required = required_by_surface[surface]
    return all(states.get(name) is CostEvidenceState.COMPLETE for name in required)


def _typed_items(
    surface: str,
    items: Sequence[Mapping[str, object]],
) -> tuple[CostGovernanceItem, ...]:
    projected: list[CostGovernanceItem] = []
    for item in items:
        if "record_count" in item:
            projected.append(CostSummaryProjection.model_validate(item))
        elif surface == "overview":
            projected.append(CostTrendProjection.model_validate(item))
        elif surface == "resource-efficiency":
            projected.append(CostResourceEfficiencyProjection.model_validate(item))
    return tuple(projected)


def _observation_readiness(
    snapshot: CostProjectionEvidenceSnapshot,
    freshness: CostEvidenceFreshness,
    *,
    truncated: bool,
) -> tuple[CostEvidenceState, CostReadinessReason | None]:
    if truncated:
        return CostEvidenceState.PARTIAL, CostReadinessReason.PROJECTION_TRUNCATED
    if snapshot.complete_count + snapshot.partial_count == 0:
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.NO_OBSERVATIONS
    if freshness is CostEvidenceFreshness.STALE:
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.OBSERVATIONS_STALE
    if snapshot.partial_count:
        return CostEvidenceState.PARTIAL, CostReadinessReason.OBSERVATIONS_PARTIAL
    return CostEvidenceState.COMPLETE, None


def _freshness(value: datetime | None, now: datetime) -> CostEvidenceFreshness:
    if value is None:
        return CostEvidenceFreshness.UNKNOWN
    if now - value > FRESHNESS_THRESHOLD:
        return CostEvidenceFreshness.STALE
    return CostEvidenceFreshness.FRESH


def _minimum_time(left: datetime | None, right: datetime | None) -> datetime | None:
    values = tuple(value for value in (left, right) if value is not None)
    return min(values) if values else None


def _maximum_time(left: datetime | None, right: datetime | None) -> datetime | None:
    values = tuple(value for value in (left, right) if value is not None)
    return max(values) if values else None


def _analytics_readiness(
    snapshot: CostProjectionEvidenceSnapshot,
    *,
    analytics: CostAnalyticsProjection | None,
    analytics_snapshot_id: str | None,
    now: datetime,
) -> tuple[CostEvidenceState, CostReadinessReason | None]:
    receipt = snapshot.latest_analytics_run
    if receipt is None:
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.ANALYTICS_RUN_MISSING
    if receipt.status.value == "failed":
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.ANALYTICS_RUN_FAILED
    if receipt.status.value == "disabled":
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.ANALYTICS_DISABLED
    if (
        analytics is None
        or analytics_snapshot_id is None
        or receipt.snapshot_id != analytics_snapshot_id
    ):
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.ANALYTICS_SNAPSHOT_MISSING
    if now - receipt.finished_at > FRESHNESS_THRESHOLD:
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.ANALYTICS_STALE
    if receipt.status.value != "complete":
        return CostEvidenceState.PARTIAL, CostReadinessReason.ANALYTICS_RUN_PARTIAL
    return CostEvidenceState.COMPLETE, None


def _count_readiness(
    *,
    count: int,
    incomplete: int,
    missing: CostReadinessReason,
    partial: CostReadinessReason,
    disclosure_allowed: bool,
    truncated: bool,
) -> tuple[CostEvidenceState, CostReadinessReason | None]:
    if not disclosure_allowed:
        return CostEvidenceState.UNAVAILABLE, CostReadinessReason.DISCLOSURE_INSUFFICIENT
    if truncated:
        return CostEvidenceState.PARTIAL, CostReadinessReason.PROJECTION_TRUNCATED
    if incomplete:
        return CostEvidenceState.PARTIAL, partial
    if not count:
        return CostEvidenceState.UNAVAILABLE, missing
    return CostEvidenceState.COMPLETE, None


def _merge_sources(
    left: Sequence[CostEvidenceSourceFacet],
    right: Sequence[CostEvidenceSourceFacet],
) -> tuple[CostEvidenceSourceFacet, ...]:
    merged = {item.source_authority: item for item in (*left, *right)}
    return tuple(merged[key] for key in sorted(merged))


__all__ = ["projection_evidence", "projection_items", "resource_candidates", "surface_complete"]
