"""Principal-scoped Outcome Assurance projection reader and Operator view builder."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import fdai_service_contracts as sc
from pydantic import Field, model_validator

from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError

FetchAll = Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]]
SummaryCardId = Literal["operational_readiness", "objective_alignment", "control_assurance"]
_CARD_IDS: tuple[SummaryCardId, ...] = (
    "operational_readiness",
    "objective_alignment",
    "control_assurance",
)


class OutcomeAssuranceSummaryCard(sc.ContractBase):
    """Read-only summary card for one Outcome Assurance pillar."""

    card_id: SummaryCardId
    state: str = Field(min_length=1, max_length=64)
    available: bool
    headline_metric: float | None = None
    unit: str | None = Field(default=None, max_length=64)
    sample_size: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    reason: sc.OutcomeAssuranceUnavailableReason | None = None
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_card_metrics(self) -> OutcomeAssuranceSummaryCard:
        for val in (self.headline_metric, self.ci_low, self.ci_high):
            if val is not None and not math.isfinite(val):
                raise ValueError("Outcome Assurance card metric values MUST be finite")
        if self.sample_size is not None and (
            isinstance(self.sample_size, bool) or self.sample_size < 0
        ):
            raise ValueError("Outcome Assurance card sample_size MUST be non-negative")
        if self.ci_low is not None and self.ci_high is not None and self.ci_low > self.ci_high:
            raise ValueError("Outcome Assurance confidence interval is inverted")
        if self.headline_metric is not None and (
            (self.ci_low is not None and self.ci_low > self.headline_metric)
            or (self.ci_high is not None and self.headline_metric > self.ci_high)
        ):
            raise ValueError("Outcome Assurance headline_metric is outside confidence interval")
        return self


def _validate_metric_item(metric: sc.OutcomeAssuranceMetric) -> None:
    for val in (metric.current_value, metric.baseline_value, metric.target_value):
        if val is not None and not math.isfinite(val):
            raise ValueError("Outcome Assurance metric values MUST be finite")
    if metric.sample_size is not None and (
        isinstance(metric.sample_size, bool) or metric.sample_size < 0
    ):
        raise ValueError("Outcome Assurance sample_size MUST be non-negative")
    ci = metric.confidence_interval
    if ci is not None:
        if not math.isfinite(ci.low) or not math.isfinite(ci.high) or ci.low > ci.high:
            raise ValueError("Outcome Assurance confidence interval bounds are invalid")
        if metric.current_value is not None and (
            ci.low > metric.current_value or metric.current_value > ci.high
        ):
            raise ValueError("Outcome Assurance confidence interval is inverted relative to value")


def _validate_metric_and_guard_uniqueness(
    outcomes: Sequence[sc.OutcomeAssuranceMetric],
    guards: Sequence[sc.OutcomeAssuranceGuardEvaluation],
) -> None:
    metric_keys = [getattr(m, "metric_id", None) or m.metric for m in outcomes]
    if len(metric_keys) != len(set(metric_keys)):
        raise ValueError("Outcome Assurance outcomes MUST NOT contain duplicate metric_id entries")
    guard_ids = [g.guard_id for g in guards]
    if len(guard_ids) != len(set(guard_ids)):
        raise ValueError(
            "Outcome Assurance guard_evaluations MUST NOT contain duplicate guard_id entries"
        )


class ObjectiveAttributionDrilldown(sc.ContractBase):
    """Objective-scoped attribution and metric evidence drill-down."""

    objective_ref: str = Field(min_length=1, max_length=512)
    state: sc.OutcomeAssuranceAttributionState
    workflow_refs: tuple[str, ...] = ()
    action_type_ids: tuple[str, ...] = ()
    finalized_events: int = Field(ge=0)
    attributed_events: int = Field(ge=0)
    unattributed_events: int = Field(ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1)
    metrics: tuple[sc.OutcomeAssuranceMetric, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: sc.OutcomeAssuranceUnavailableReason | None = None

    @model_validator(mode="after")
    def _validate_drilldown_metrics(self) -> ObjectiveAttributionDrilldown:
        _validate_metric_and_guard_uniqueness(self.metrics, ())
        return self


class OutcomeAssuranceOperatorProjection(sc.ContractBase):
    """Authenticated read-only Operator projection with summary cards and drill-downs."""

    type: Literal["outcome-assurance.operator-projection"] = "outcome-assurance.operator-projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    read_only: Literal[True] = True
    authority: Literal["none"] = "none"
    principal_id: str = Field(min_length=1, max_length=512)
    state: sc.OutcomeAssuranceReadState
    reason: sc.OutcomeAssuranceUnavailableReason | None = None
    scope: sc.OutcomeAssuranceScope
    window: sc.OutcomeAssuranceWindow
    summary_cards: tuple[OutcomeAssuranceSummaryCard, ...]
    objective_drilldowns: tuple[ObjectiveAttributionDrilldown, ...]
    guard_status: sc.OutcomeAssuranceControlSummary
    projection: sc.OutcomeAssuranceProjection
    projection_digest: str = Field(default="")

    @model_validator(mode="after")
    def _validate_and_finalize_digest(self) -> OutcomeAssuranceOperatorProjection:
        _validate_metric_and_guard_uniqueness(
            self.projection.outcomes, self.guard_status.guard_evaluations
        )
        _validate_metric_and_guard_uniqueness(
            self.projection.outcomes, self.projection.guards.guard_evaluations
        )
        material = self.model_dump(mode="json", exclude={"projection_digest"})
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        expected = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        if not self.projection_digest:
            object.__setattr__(self, "projection_digest", expected)
        elif self.projection_digest != expected:
            raise ValueError("Outcome Assurance projection_digest mismatch")
        return self

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_json(self) -> dict[str, object]:
        return self.model_dump(mode="json")


async def read_outcome_assurance_projection(
    *, fetch_all: FetchAll, query: ProjectionQuery
) -> Mapping[str, object]:
    """Read one retained Outcome Assurance projection without synthesizing values."""
    now = datetime.now(UTC)
    scope_ref = _bounded_param(query, "scope_ref", default="global", maximum=512)
    vertical = _last(query.params.get("vertical"))
    window_label = _bounded_param(query, "window", default="30d", maximum=64)
    if vertical is not None and vertical not in {"resilience", "change_safety", "cost_governance"}:
        raise ProjectionUnavailableError("Outcome Assurance vertical is malformed")
    window = _outcome_assurance_window(window_label, now)
    scope = sc.OutcomeAssuranceScope.model_validate({"scope_ref": scope_ref, "vertical": vertical})
    key = _outcome_assurance_key(query.principal_id, scope_ref, vertical, window_label)
    rows = await fetch_all("SELECT value FROM state_kv WHERE key = %s", (key,))
    if not rows:
        reason = sc.OutcomeAssuranceUnavailableReason.PROJECTION_MISSING
        return _outcome_assurance_unavailable(scope, window, reason, now).model_dump(mode="json")
    try:
        raw_value = rows[0].get("value")
        if isinstance(raw_value, Mapping) and "revision" in raw_value:
            raw_value = {k: v for k, v in raw_value.items() if k != "revision"}
        projection = sc.OutcomeAssuranceProjection.model_validate(raw_value)
        _validate_metric_and_guard_uniqueness(
            projection.outcomes, projection.guards.guard_evaluations
        )
        for item in projection.outcomes:
            _validate_metric_item(item)
    except (TypeError, ValueError):
        reason = sc.OutcomeAssuranceUnavailableReason.PROJECTION_MALFORMED
        return _outcome_assurance_unavailable(scope, window, reason, now).model_dump(mode="json")
    if _outcome_assurance_is_stale(projection, now):
        return _stale_outcome_assurance_projection(projection, now).model_dump(mode="json")
    return projection.model_dump(mode="json")


def _bounded_param(query: ProjectionQuery, name: str, *, default: str, maximum: int) -> str:
    value = _last(query.params.get(name)) or default
    if not value.strip() or len(value) > maximum or "\x00" in value:
        raise ProjectionUnavailableError(f"Outcome Assurance {name} is malformed")
    return value


def _outcome_assurance_window(value: str, now: datetime) -> sc.OutcomeAssuranceWindow:
    if value.endswith("d") and value[:-1].isdigit() and 1 <= (days := int(value[:-1])) <= 366:
        return sc.OutcomeAssuranceWindow(start=now - timedelta(days=days), end=now, label=value)
    raise ProjectionUnavailableError("Outcome Assurance window is malformed")


def _outcome_assurance_key(
    principal_id: str, scope_ref: str, vertical: str | None, window: str
) -> str:
    identity = "\0".join((principal_id, scope_ref, vertical or "", window))
    return f"outcome-assurance:projection:v1:{hashlib.sha256(identity.encode()).hexdigest()}"


def _outcome_assurance_unavailable(
    scope: sc.OutcomeAssuranceScope,
    window: sc.OutcomeAssuranceWindow,
    reason: sc.OutcomeAssuranceUnavailableReason,
    now: datetime,
) -> sc.OutcomeAssuranceProjection:
    src = "outcome-assurance-measurement"
    align = {
        "state": "unavailable",
        "finalized_events": 0,
        "attributed_events": 0,
        "unattributed_events": 0,
        "reason": reason,
    }
    data = {
        "state": "unavailable",
        "reason": reason,
        "scope": scope,
        "window": window,
        "sources": [{"name": src, "state": "unavailable", "reason": reason}],
        "readiness": [{"facet": "measurement", "state": "unavailable", "reason": reason}],
        "alignment": align,
        "outcomes": [],
        "guards": {"state": "unavailable", "reason": reason},
        "provenance": {"as_of": now, "generated_at": now, "source_names": [src]},
    }
    return sc.OutcomeAssuranceProjection.model_validate(data)


def _outcome_assurance_is_stale(projection: sc.OutcomeAssuranceProjection, now: datetime) -> bool:
    stale_src = any(
        s.state is sc.OutcomeAssuranceSourceState.COMPLETE and s.expires_at and s.expires_at <= now
        for s in projection.sources
    )
    return stale_src or any(
        r.expires_at is not None and r.expires_at <= now for r in projection.readiness
    )


def _stale_outcome_assurance_projection(
    projection: sc.OutcomeAssuranceProjection, now: datetime
) -> sc.OutcomeAssuranceProjection:
    reason = sc.OutcomeAssuranceUnavailableReason.SOURCE_STALE
    keep = {
        sc.OutcomeAssuranceReadinessState.UNKNOWN,
        sc.OutcomeAssuranceReadinessState.UNAVAILABLE,
        sc.OutcomeAssuranceReadinessState.STALE,
    }
    sources = tuple(
        s.model_copy(update={"state": sc.OutcomeAssuranceSourceState.STALE, "reason": reason})
        if s.state is sc.OutcomeAssuranceSourceState.COMPLETE
        else s
        for s in projection.sources
    )
    readiness = tuple(
        r.model_copy(update={"state": sc.OutcomeAssuranceReadinessState.STALE, "reason": reason})
        if r.state not in keep
        else r
        for r in projection.readiness
    )
    outcomes = [
        o.model_dump(include={"objective_ref", "metric", "evidence_refs"})
        | {"state": "stale", "reason": reason}
        for o in projection.outcomes
    ]
    ev, p = projection.alignment.finalized_events, projection.provenance
    align = {
        "state": "unavailable",
        "finalized_events": ev,
        "attributed_events": 0,
        "unattributed_events": ev,
        "reason": reason,
    }
    data = {
        "state": "stale",
        "reason": reason,
        "scope": projection.scope,
        "window": projection.window,
        "sources": sources,
        "readiness": readiness,
        "alignment": align,
        "outcomes": outcomes,
        "guards": {"state": "stale", "reason": reason},
        "provenance": {"as_of": p.as_of, "generated_at": now, "source_names": p.source_names},
    }
    return sc.OutcomeAssuranceProjection.model_validate(data)


def build_outcome_assurance_operator_projection(
    *,
    principal_id: str | None,
    projection: sc.OutcomeAssuranceProjection | None,
    scope_ref: str = "global",
    vertical: str | None = None,
    window_label: str = "30d",
    now: datetime | None = None,
) -> OutcomeAssuranceOperatorProjection:
    """Build an authenticated read-only Operator projection without synthetic values."""
    if principal_id is None or not principal_id.strip():
        raise PermissionError("Outcome Assurance projection requires an authenticated principal")
    current_now = now or datetime.now(UTC)
    if projection is None:
        window = _outcome_assurance_window(window_label, current_now)
        scope = sc.OutcomeAssuranceScope.model_validate(
            {"scope_ref": scope_ref, "vertical": vertical}
        )
        reason = sc.OutcomeAssuranceUnavailableReason.PROJECTION_MISSING
        return _unavailable_operator_projection(
            principal_id, _outcome_assurance_unavailable(scope, window, reason, current_now), reason
        )
    if (
        _outcome_assurance_is_stale(projection, current_now)
        or projection.state is sc.OutcomeAssuranceReadState.STALE
    ):
        stale = _stale_outcome_assurance_projection(projection, current_now)
        return _unavailable_operator_projection(
            principal_id, stale, sc.OutcomeAssuranceUnavailableReason.SOURCE_STALE
        )
    bad = next(
        (s for s in projection.sources if s.state is not sc.OutcomeAssuranceSourceState.COMPLETE),
        None,
    )
    if (
        not projection.sources
        or bad is not None
        or projection.state is not sc.OutcomeAssuranceReadState.COMPLETE
    ):
        reason = (
            (bad.reason if bad is not None else None)
            or projection.reason
            or sc.OutcomeAssuranceUnavailableReason.SOURCE_MISSING
        )
        unavail = _outcome_assurance_unavailable(
            projection.scope, projection.window, reason, current_now
        )
        return _unavailable_operator_projection(principal_id, unavail, reason)
    if projection.alignment.coverage is not None and not math.isfinite(
        projection.alignment.coverage
    ):
        raise ValueError("Outcome Assurance alignment coverage MUST be finite")
    _validate_metric_and_guard_uniqueness(projection.outcomes, projection.guards.guard_evaluations)
    for item in projection.outcomes:
        _validate_metric_item(item)
    for g in projection.guards.guard_evaluations:
        if not math.isfinite(g.threshold) or not math.isfinite(g.observed_value):
            raise ValueError("Outcome Assurance guard evaluation values MUST be finite")
    return OutcomeAssuranceOperatorProjection.model_validate(
        {
            "principal_id": principal_id,
            "state": sc.OutcomeAssuranceReadState.COMPLETE,
            "reason": None,
            "scope": projection.scope,
            "window": projection.window,
            "summary_cards": _build_summary_cards(projection),
            "objective_drilldowns": _build_objective_drilldowns(projection),
            "guard_status": projection.guards,
            "projection": projection,
        }
    )


async def read_outcome_assurance_operator_projection(
    *, fetch_all: FetchAll, query: ProjectionQuery
) -> Mapping[str, object]:
    """Read and build the authenticated Operator Outcome Assurance projection."""
    if not query.principal_id.strip():
        raise PermissionError("Outcome Assurance projection requires an authenticated principal")
    raw = await read_outcome_assurance_projection(fetch_all=fetch_all, query=query)
    parsed = sc.OutcomeAssuranceProjection.model_validate(raw)
    return build_outcome_assurance_operator_projection(
        principal_id=query.principal_id, projection=parsed
    ).model_dump(mode="json")


def _card(
    card_id: SummaryCardId,
    state: str,
    available: bool,
    metric: float | None = None,
    reason: sc.OutcomeAssuranceUnavailableReason | None = None,
    refs: tuple[str, ...] = (),
) -> OutcomeAssuranceSummaryCard:
    return OutcomeAssuranceSummaryCard.model_validate(
        {
            "card_id": card_id,
            "state": state,
            "available": available,
            "headline_metric": metric,
            "unit": "ratio" if metric is not None else None,
            "reason": reason,
            "evidence_refs": refs,
        }
    )


def _unavailable_operator_projection(
    principal_id: str,
    projection: sc.OutcomeAssuranceProjection,
    reason: sc.OutcomeAssuranceUnavailableReason,
) -> OutcomeAssuranceOperatorProjection:
    cards = tuple(_card(cid, "unavailable", False, reason=reason) for cid in _CARD_IDS)
    return OutcomeAssuranceOperatorProjection.model_validate(
        {
            "principal_id": principal_id,
            "state": sc.OutcomeAssuranceReadState.UNAVAILABLE,
            "reason": reason,
            "scope": projection.scope,
            "window": projection.window,
            "summary_cards": cards,
            "objective_drilldowns": (),
            "guard_status": {"state": "unavailable", "reason": reason},
            "projection": projection,
        }
    )


def _build_summary_cards(
    projection: sc.OutcomeAssuranceProjection,
) -> tuple[OutcomeAssuranceSummaryCard, ...]:
    facets, align, guards = projection.readiness, projection.alignment, projection.guards
    ready_n = sum(1 for f in facets if f.state is sc.OutcomeAssuranceReadinessState.READY)
    blocked = any(f.state is sc.OutcomeAssuranceReadinessState.BLOCKED for f in facets)
    unavail = not facets or any(
        f.state
        in {sc.OutcomeAssuranceReadinessState.UNAVAILABLE, sc.OutcomeAssuranceReadinessState.STALE}
        for f in facets
    )
    r_state = (
        "unavailable"
        if unavail
        else ("blocked" if blocked else ("ready" if ready_n == len(facets) else "observed"))
    )
    r_refs = tuple(sorted({ref for f in facets for ref in f.evidence_refs}))
    g_evals = guards.guard_evaluations
    passed_g = sum(1 for g in g_evals if g.passed)
    g_refs = tuple(sorted(set(guards.evidence_refs) | {g.evidence_ref for g in g_evals}))
    g_unavail = guards.state in {
        sc.OutcomeAssuranceGuardState.UNAVAILABLE,
        sc.OutcomeAssuranceGuardState.STALE,
    }
    a_avail = align.state is not sc.OutcomeAssuranceAttributionState.UNAVAILABLE
    r_metric = None if unavail else ready_n / len(facets)
    g_metric = (passed_g / len(g_evals)) if g_evals else None
    c1 = _card("operational_readiness", r_state, not unavail, r_metric, refs=r_refs)
    c2 = _card(
        "objective_alignment",
        align.state.value,
        a_avail,
        align.coverage,
        align.reason,
        align.evidence_refs,
    )
    c3 = _card(
        "control_assurance", guards.state.value, not g_unavail, g_metric, guards.reason, g_refs
    )
    return (c1, c2, c3)


def _build_objective_drilldowns(
    projection: sc.OutcomeAssuranceProjection,
) -> tuple[ObjectiveAttributionDrilldown, ...]:
    align = projection.alignment
    by_obj: dict[str, list[sc.OutcomeAssuranceMetric]] = {}
    for metric in projection.outcomes:
        by_obj.setdefault(metric.objective_ref, []).append(metric)
    keys = {
        "state",
        "workflow_refs",
        "action_type_ids",
        "finalized_events",
        "attributed_events",
        "unattributed_events",
        "coverage",
        "reason",
    }
    base = align.model_dump(include=keys)
    items: list[ObjectiveAttributionDrilldown] = []
    for obj in sorted(set(align.objective_refs) | set(by_obj)):
        metrics = tuple(by_obj.get(obj, ()))
        m_refs = {r for m in metrics for r in m.evidence_refs}
        refs = tuple(sorted(set(align.evidence_refs) | m_refs))
        items.append(
            ObjectiveAttributionDrilldown.model_validate(
                {**base, "objective_ref": obj, "metrics": metrics, "evidence_refs": refs}
            )
        )
    return tuple(items)


def _last(values: tuple[str, ...] | None) -> str | None:
    return values[-1] if values else None


__all__ = [
    "ObjectiveAttributionDrilldown",
    "OutcomeAssuranceOperatorProjection",
    "OutcomeAssuranceSummaryCard",
    "build_outcome_assurance_operator_projection",
    "read_outcome_assurance_operator_projection",
    "read_outcome_assurance_projection",
]
