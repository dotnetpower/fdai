"""Principal-scoped Outcome Assurance projection reader helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts import (
    OutcomeAssuranceAttribution,
    OutcomeAssuranceAttributionState,
    OutcomeAssuranceControlSummary,
    OutcomeAssuranceGuardState,
    OutcomeAssuranceMetric,
    OutcomeAssuranceMetricState,
    OutcomeAssuranceProjection,
    OutcomeAssuranceProvenance,
    OutcomeAssuranceReadiness,
    OutcomeAssuranceReadinessFacet,
    OutcomeAssuranceReadinessState,
    OutcomeAssuranceReadState,
    OutcomeAssuranceScope,
    OutcomeAssuranceSource,
    OutcomeAssuranceSourceState,
    OutcomeAssuranceUnavailableReason,
    OutcomeAssuranceWindow,
)

from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError

FetchAll = Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]]


async def read_outcome_assurance_projection(
    *,
    fetch_all: FetchAll,
    query: ProjectionQuery,
) -> Mapping[str, object]:
    """Read one retained Outcome Assurance projection without synthesizing values."""

    now = datetime.now(UTC)
    scope_ref = _bounded_param(query, "scope_ref", default="global", maximum=512)
    vertical = _last(query.params.get("vertical"))
    window_label = _bounded_param(query, "window", default="30d", maximum=64)
    if vertical is not None and vertical not in {
        "resilience",
        "change_safety",
        "cost_governance",
    }:
        raise ProjectionUnavailableError("Outcome Assurance vertical is malformed")
    window = _outcome_assurance_window(window_label, now)
    scope = OutcomeAssuranceScope.model_validate(
        {
            "scope_ref": scope_ref,
            "vertical": vertical,
        }
    )
    key = _outcome_assurance_key(
        principal_id=query.principal_id,
        scope_ref=scope_ref,
        vertical=vertical,
        window=window_label,
    )
    rows = await fetch_all("SELECT value FROM state_kv WHERE key = %s", (key,))
    if not rows:
        return _outcome_assurance_unavailable(
            scope=scope,
            window=window,
            reason=OutcomeAssuranceUnavailableReason.PROJECTION_MISSING,
            now=now,
        ).model_dump(mode="json")
    try:
        projection = OutcomeAssuranceProjection.model_validate(rows[0].get("value"))
    except (TypeError, ValueError):
        return _outcome_assurance_unavailable(
            scope=scope,
            window=window,
            reason=OutcomeAssuranceUnavailableReason.PROJECTION_MALFORMED,
            now=now,
        ).model_dump(mode="json")
    if _outcome_assurance_is_stale(projection, now):
        return _stale_outcome_assurance_projection(projection, now).model_dump(mode="json")
    return projection.model_dump(mode="json")


def _bounded_param(
    query: ProjectionQuery,
    name: str,
    *,
    default: str,
    maximum: int,
) -> str:
    value = _last(query.params.get(name)) or default
    if not value.strip() or len(value) > maximum or "\x00" in value:
        raise ProjectionUnavailableError(f"Outcome Assurance {name} is malformed")
    return value


def _outcome_assurance_window(value: str, now: datetime) -> OutcomeAssuranceWindow:
    if value.endswith("d") and value[:-1].isdigit():
        days = int(value[:-1])
        if 1 <= days <= 366:
            return OutcomeAssuranceWindow(
                start=now - timedelta(days=days),
                end=now,
                label=value,
            )
    raise ProjectionUnavailableError("Outcome Assurance window is malformed")


def _outcome_assurance_key(
    *,
    principal_id: str,
    scope_ref: str,
    vertical: str | None,
    window: str,
) -> str:
    identity = "\0".join((principal_id, scope_ref, vertical or "", window))
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"outcome-assurance:projection:v1:{digest}"


def _outcome_assurance_unavailable(
    *,
    scope: OutcomeAssuranceScope,
    window: OutcomeAssuranceWindow,
    reason: OutcomeAssuranceUnavailableReason,
    now: datetime,
) -> OutcomeAssuranceProjection:
    source_name = "outcome-assurance-measurement"
    return OutcomeAssuranceProjection(
        state=OutcomeAssuranceReadState.UNAVAILABLE,
        reason=reason,
        scope=scope,
        window=window,
        sources=(
            OutcomeAssuranceSource(
                name=source_name,
                state=OutcomeAssuranceSourceState.UNAVAILABLE,
                reason=reason,
            ),
        ),
        readiness=(
            OutcomeAssuranceReadiness(
                facet=OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=OutcomeAssuranceReadinessState.UNAVAILABLE,
                reason=reason,
            ),
        ),
        alignment=OutcomeAssuranceAttribution(
            state=OutcomeAssuranceAttributionState.UNAVAILABLE,
            finalized_events=0,
            attributed_events=0,
            unattributed_events=0,
            reason=reason,
        ),
        outcomes=(),
        guards=OutcomeAssuranceControlSummary(
            state=OutcomeAssuranceGuardState.UNAVAILABLE,
            reason=reason,
        ),
        provenance=OutcomeAssuranceProvenance(
            as_of=now,
            generated_at=now,
            source_names=(source_name,),
        ),
    )


def _outcome_assurance_is_stale(
    projection: OutcomeAssuranceProjection,
    now: datetime,
) -> bool:
    for source in projection.sources:
        if source.state is not OutcomeAssuranceSourceState.COMPLETE:
            continue
        if source.expires_at is not None and source.expires_at <= now:
            return True
    for readiness in projection.readiness:
        if readiness.expires_at is not None and readiness.expires_at <= now:
            return True
    return False


def _stale_outcome_assurance_projection(
    projection: OutcomeAssuranceProjection,
    now: datetime,
) -> OutcomeAssuranceProjection:
    reason = OutcomeAssuranceUnavailableReason.SOURCE_STALE
    sources = tuple(
        OutcomeAssuranceSource(
            name=source.name,
            state=OutcomeAssuranceSourceState.STALE,
            reason=reason,
            observed_at=source.observed_at,
            expires_at=source.expires_at,
            evidence_refs=source.evidence_refs,
        )
        if source.state is OutcomeAssuranceSourceState.COMPLETE
        else source
        for source in projection.sources
    )
    readiness = tuple(
        OutcomeAssuranceReadiness(
            facet=item.facet,
            state=OutcomeAssuranceReadinessState.STALE,
            reason=reason,
            observed_at=item.observed_at,
            expires_at=item.expires_at,
            evidence_refs=item.evidence_refs,
        )
        if item.state
        not in {
            OutcomeAssuranceReadinessState.UNKNOWN,
            OutcomeAssuranceReadinessState.UNAVAILABLE,
            OutcomeAssuranceReadinessState.STALE,
        }
        else item
        for item in projection.readiness
    )
    outcomes = tuple(
        OutcomeAssuranceMetric(
            objective_ref=outcome.objective_ref,
            metric=outcome.metric,
            state=OutcomeAssuranceMetricState.STALE,
            reason=reason,
            evidence_refs=outcome.evidence_refs,
        )
        for outcome in projection.outcomes
    )
    return OutcomeAssuranceProjection(
        state=OutcomeAssuranceReadState.STALE,
        reason=reason,
        scope=projection.scope,
        window=projection.window,
        sources=sources,
        readiness=readiness,
        alignment=OutcomeAssuranceAttribution(
            state=OutcomeAssuranceAttributionState.UNAVAILABLE,
            finalized_events=projection.alignment.finalized_events,
            attributed_events=0,
            unattributed_events=projection.alignment.finalized_events,
            reason=reason,
        ),
        outcomes=outcomes,
        guards=OutcomeAssuranceControlSummary(
            state=OutcomeAssuranceGuardState.STALE,
            reason=reason,
        ),
        provenance=OutcomeAssuranceProvenance(
            as_of=projection.provenance.as_of,
            generated_at=now,
            source_names=projection.provenance.source_names,
        ),
    )


def _last(values: tuple[str, ...] | None) -> str | None:
    return values[-1] if values else None


__all__ = ["read_outcome_assurance_projection"]
