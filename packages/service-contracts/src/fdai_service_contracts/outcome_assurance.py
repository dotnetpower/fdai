"""Versioned, authority-free Outcome Assurance read contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.executor_models import ContractBase

BoundedText = Annotated[str, Field(min_length=1, max_length=512)]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,191}$")]


class OutcomeAssuranceReadState(StrEnum):
    """Terminal state of the read-only Outcome Assurance projection."""

    COMPLETE = "complete"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class OutcomeAssuranceUnavailableReason(StrEnum):
    """Typed reason that the projection cannot make a measured claim."""

    SOURCE_NOT_CONNECTED = "source_not_connected"
    SOURCE_MISSING = "source_missing"
    SOURCE_STALE = "source_stale"
    PROJECTION_MISSING = "projection_missing"
    PROJECTION_MALFORMED = "projection_malformed"
    PRINCIPAL_SCOPE_EMPTY = "principal_scope_empty"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


class OutcomeAssuranceVertical(StrEnum):
    """Supported operating vertical filters."""

    RESILIENCE = "resilience"
    CHANGE_SAFETY = "change_safety"
    COST_GOVERNANCE = "cost_governance"


class OutcomeAssuranceSourceState(StrEnum):
    """Qualification state for one authoritative source."""

    COMPLETE = "complete"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class OutcomeAssuranceReadinessFacet(StrEnum):
    """Readiness facets composed by the Outcome Assurance projection."""

    PLATFORM = "platform"
    EVIDENCE = "evidence"
    DETECTION = "detection"
    ACTION_SAFETY = "action_safety"
    OPERATIONAL_HANDOFF = "operational_handoff"
    MEASUREMENT = "measurement"
    PROMOTION = "promotion"


class OutcomeAssuranceReadinessState(StrEnum):
    """Freshness-bound readiness state for one existing owner."""

    UNKNOWN = "unknown"
    BLOCKED = "blocked"
    OBSERVED = "observed"
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class OutcomeAssuranceAttributionState(StrEnum):
    """Coverage-preserving attribution state."""

    UNATTRIBUTED = "unattributed"
    PARTIAL = "partial"
    ATTRIBUTED = "attributed"
    UNAVAILABLE = "unavailable"


class OutcomeAssuranceMetricState(StrEnum):
    """Evidence state for one objective measurement."""

    MEASURED = "measured"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    REGRESSED = "regressed"


class OutcomeAssuranceGuardState(StrEnum):
    """Control assurance state without approval or execution authority."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    ATTENTION = "attention"
    BLOCKED = "blocked"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class OutcomeAssuranceScope(ContractBase):
    """Pinned scope identity for one authenticated read."""

    scope_ref: BoundedText
    service_refs: Annotated[tuple[BoundedText, ...], Field(max_length=32)] = ()
    workload_refs: Annotated[tuple[BoundedText, ...], Field(max_length=32)] = ()
    vertical: OutcomeAssuranceVertical | None = None

    @field_validator("service_refs", "workload_refs")
    @classmethod
    def require_unique_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Outcome Assurance scope refs MUST be unique")
        return value


class OutcomeAssuranceWindow(ContractBase):
    """Time-bounded evidence window shared by all projection groups."""

    start: datetime
    end: datetime
    label: Annotated[str | None, Field(max_length=64)] = None
    scenario_set_version: BoundedText | None = None

    @field_validator("start", "end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance window timestamps MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> OutcomeAssuranceWindow:
        if self.end <= self.start:
            raise ValueError("Outcome Assurance window end MUST follow start")
        return self


class OutcomeAssuranceSource(ContractBase):
    """One authoritative source binding and freshness state."""

    name: BoundedText
    state: OutcomeAssuranceSourceState
    reason: OutcomeAssuranceUnavailableReason | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_refs: Annotated[tuple[BoundedText, ...], Field(max_length=32)] = ()

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance source timestamps MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_source(self) -> OutcomeAssuranceSource:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Outcome Assurance source evidence refs MUST be unique")
        if (self.observed_at is None) != (self.expires_at is None):
            raise ValueError("Outcome Assurance source freshness requires both timestamps")
        if self.observed_at is not None and self.expires_at is not None:
            if self.expires_at <= self.observed_at:
                raise ValueError("Outcome Assurance source expiry MUST follow observation")
        if self.state is OutcomeAssuranceSourceState.COMPLETE:
            if self.reason is not None:
                raise ValueError("complete Outcome Assurance source cannot carry a reason")
            if not self.evidence_refs or self.observed_at is None:
                raise ValueError("complete Outcome Assurance source MUST cite fresh evidence")
        elif self.reason is None:
            raise ValueError("non-complete Outcome Assurance source requires a typed reason")
        return self


class OutcomeAssuranceReadiness(ContractBase):
    """Freshness-bound state for one readiness facet."""

    facet: OutcomeAssuranceReadinessFacet
    state: OutcomeAssuranceReadinessState
    reason: OutcomeAssuranceUnavailableReason | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_refs: Annotated[tuple[BoundedText, ...], Field(max_length=32)] = ()

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance readiness timestamps MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_readiness(self) -> OutcomeAssuranceReadiness:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Outcome Assurance readiness evidence refs MUST be unique")
        if (self.observed_at is None) != (self.expires_at is None):
            raise ValueError("Outcome Assurance readiness freshness requires both timestamps")
        if self.observed_at is not None and self.expires_at is not None:
            if self.expires_at <= self.observed_at:
                raise ValueError("Outcome Assurance readiness expiry MUST follow observation")
        if self.state in {
            OutcomeAssuranceReadinessState.STALE,
            OutcomeAssuranceReadinessState.UNAVAILABLE,
        }:
            if self.reason is None:
                raise ValueError("unavailable or stale readiness requires a typed reason")
        elif self.reason is not None:
            raise ValueError("available readiness cannot carry an unavailable reason")
        if self.state not in {
            OutcomeAssuranceReadinessState.UNKNOWN,
            OutcomeAssuranceReadinessState.UNAVAILABLE,
        } and (not self.evidence_refs or self.observed_at is None):
            raise ValueError("available readiness MUST cite fresh evidence")
        return self


class OutcomeAssuranceAttribution(ContractBase):
    """Objective attribution accounting for finalized events."""

    state: OutcomeAssuranceAttributionState
    finalized_events: Annotated[int, Field(strict=True, ge=0)]
    attributed_events: Annotated[int, Field(strict=True, ge=0)]
    unattributed_events: Annotated[int, Field(strict=True, ge=0)]
    coverage: Annotated[float | None, Field(ge=0, le=1)] = None
    objective_refs: Annotated[tuple[BoundedText, ...], Field(max_length=64)] = ()
    workflow_refs: Annotated[tuple[BoundedText, ...], Field(max_length=64)] = ()
    action_type_ids: Annotated[tuple[BoundedText, ...], Field(max_length=64)] = ()
    evidence_refs: Annotated[tuple[BoundedText, ...], Field(max_length=64)] = ()
    reason: OutcomeAssuranceUnavailableReason | None = None

    @model_validator(mode="after")
    def validate_attribution(self) -> OutcomeAssuranceAttribution:
        for label, values in (
            ("objective refs", self.objective_refs),
            ("workflow refs", self.workflow_refs),
            ("action type ids", self.action_type_ids),
            ("evidence refs", self.evidence_refs),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Outcome Assurance attribution {label} MUST be unique")
        if self.finalized_events != self.attributed_events + self.unattributed_events:
            raise ValueError("finalized_events MUST equal attributed_events + unattributed_events")
        if self.state is OutcomeAssuranceAttributionState.UNAVAILABLE:
            if self.reason is None:
                raise ValueError("unavailable attribution requires a typed reason")
            if self.coverage is not None or self.attributed_events != 0:
                raise ValueError("unavailable attribution cannot carry measured coverage")
            return self
        if self.reason is not None:
            raise ValueError("available attribution cannot carry an unavailable reason")
        expected = (
            0.0 if self.finalized_events == 0 else self.attributed_events / self.finalized_events
        )
        if self.coverage is None or abs(self.coverage - expected) > 1e-9:
            raise ValueError("Outcome Assurance attribution coverage MUST match event counts")
        if self.attributed_events > 0 and (not self.evidence_refs or not self.objective_refs):
            raise ValueError("attributed Outcome Assurance events MUST cite objective evidence")
        return self


class OutcomeAssuranceConfidenceInterval(ContractBase):
    """Confidence interval for one measured outcome."""

    low: float
    high: float

    @model_validator(mode="after")
    def validate_interval(self) -> OutcomeAssuranceConfidenceInterval:
        if self.high < self.low:
            raise ValueError("Outcome Assurance confidence interval high MUST be >= low")
        return self


class OutcomeAssuranceMetric(ContractBase):
    """One objective metric without synthetic or zero-filled values."""

    objective_ref: BoundedText
    metric: ReasonCode
    state: OutcomeAssuranceMetricState
    reason: OutcomeAssuranceUnavailableReason | None = None
    current_value: float | None = None
    baseline_value: float | None = None
    target_value: float | None = None
    unit: Annotated[str | None, Field(max_length=64)] = None
    sample_size: Annotated[int | None, Field(strict=True, ge=0)] = None
    confidence_interval: OutcomeAssuranceConfidenceInterval | None = None
    source_time: datetime | None = None
    evidence_refs: Annotated[tuple[BoundedText, ...], Field(max_length=32)] = ()

    @field_validator("source_time")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance metric source_time MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_metric(self) -> OutcomeAssuranceMetric:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Outcome Assurance metric evidence refs MUST be unique")
        values = (
            self.current_value,
            self.baseline_value,
            self.target_value,
            self.unit,
            self.sample_size,
            self.confidence_interval,
            self.source_time,
        )
        if self.state in {
            OutcomeAssuranceMetricState.MEASURED,
            OutcomeAssuranceMetricState.REGRESSED,
        }:
            if any(value is None for value in values) or not self.evidence_refs:
                raise ValueError("measured Outcome Assurance metric MUST carry full evidence")
            if self.reason is not None:
                raise ValueError("measured Outcome Assurance metric cannot carry a reason")
        else:
            if any(value is not None for value in values):
                raise ValueError("unavailable Outcome Assurance metric cannot carry values")
            if self.reason is None:
                raise ValueError("unavailable Outcome Assurance metric requires a typed reason")
        return self


class OutcomeAssuranceGuardEvaluation(ContractBase):
    """One guard threshold result carried into the read model."""

    guard_id: BoundedText
    threshold: float
    observed_value: float
    passed: bool
    evidence_ref: BoundedText


class OutcomeAssuranceControlSummary(ContractBase):
    """Control assurance without approval, promotion, or execution authority."""

    state: OutcomeAssuranceGuardState
    reason: OutcomeAssuranceUnavailableReason | None = None
    guard_evaluations: Annotated[
        tuple[OutcomeAssuranceGuardEvaluation, ...],
        Field(max_length=64),
    ] = ()
    policy_escape_count: Annotated[int, Field(strict=True, ge=0)] = 0
    evidence_refs: Annotated[tuple[BoundedText, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def validate_control_summary(self) -> OutcomeAssuranceControlSummary:
        guard_ids = [item.guard_id for item in self.guard_evaluations]
        if len(guard_ids) != len(set(guard_ids)):
            raise ValueError("Outcome Assurance guard evaluations MUST be unique")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Outcome Assurance guard evidence refs MUST be unique")
        if self.state in {
            OutcomeAssuranceGuardState.STALE,
            OutcomeAssuranceGuardState.UNAVAILABLE,
        }:
            if self.reason is None:
                raise ValueError("unavailable or stale guards require a typed reason")
            if self.guard_evaluations or self.policy_escape_count:
                raise ValueError("unavailable or stale guards cannot carry measured values")
            return self
        if self.reason is not None:
            raise ValueError("available guards cannot carry an unavailable reason")
        if self.policy_escape_count > 0 and self.state is not OutcomeAssuranceGuardState.BLOCKED:
            raise ValueError("policy escapes MUST force blocked Outcome Assurance guards")
        if self.state is not OutcomeAssuranceGuardState.UNKNOWN and not self.evidence_refs:
            raise ValueError("available Outcome Assurance guards MUST cite evidence")
        return self


class OutcomeAssuranceProvenance(ContractBase):
    """Pinned source set and as-of time for one projection response."""

    as_of: datetime
    generated_at: datetime
    source_names: Annotated[tuple[BoundedText, ...], Field(max_length=16)]
    synthetic: Literal[False] = False

    @field_validator("as_of", "generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance provenance timestamps MUST be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_provenance(self) -> OutcomeAssuranceProvenance:
        if self.generated_at < self.as_of:
            raise ValueError("Outcome Assurance generated_at MUST NOT precede as_of")
        if len(self.source_names) != len(set(self.source_names)):
            raise ValueError("Outcome Assurance provenance source names MUST be unique")
        return self


class OutcomeAssuranceProjection(ContractBase):
    """Authenticated, read-only Operator projection for Outcome Assurance."""

    type: Literal["outcome-assurance.projection"] = "outcome-assurance.projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    state: OutcomeAssuranceReadState
    reason: OutcomeAssuranceUnavailableReason | None = None
    scope: OutcomeAssuranceScope
    window: OutcomeAssuranceWindow
    sources: Annotated[tuple[OutcomeAssuranceSource, ...], Field(max_length=16)]
    readiness: Annotated[tuple[OutcomeAssuranceReadiness, ...], Field(max_length=16)] = ()
    alignment: OutcomeAssuranceAttribution
    outcomes: Annotated[tuple[OutcomeAssuranceMetric, ...], Field(max_length=64)] = ()
    guards: OutcomeAssuranceControlSummary
    provenance: OutcomeAssuranceProvenance
    principal_scoped: Literal[True] = True
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_projection(self) -> OutcomeAssuranceProjection:
        source_names = tuple(source.name for source in self.sources)
        if len(source_names) != len(set(source_names)):
            raise ValueError("Outcome Assurance sources MUST be unique")
        if self.provenance.source_names != source_names:
            raise ValueError("Outcome Assurance provenance source names MUST match sources")
        facets = [item.facet for item in self.readiness]
        if len(facets) != len(set(facets)):
            raise ValueError("Outcome Assurance readiness facets MUST be unique")
        metric_keys = [(item.objective_ref, item.metric) for item in self.outcomes]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("Outcome Assurance outcomes MUST be unique by objective and metric")
        source_states = {source.state for source in self.sources}
        if self.state is OutcomeAssuranceReadState.COMPLETE:
            if self.reason is not None:
                raise ValueError("complete Outcome Assurance projection cannot carry a reason")
            if not self.sources or source_states != {OutcomeAssuranceSourceState.COMPLETE}:
                raise ValueError("complete Outcome Assurance projection requires complete sources")
        else:
            if self.reason is None:
                raise ValueError("non-complete Outcome Assurance projection requires a reason")
            if self.state is OutcomeAssuranceReadState.STALE:
                if OutcomeAssuranceSourceState.STALE not in source_states:
                    raise ValueError("stale Outcome Assurance projection requires a stale source")
            if self.state is OutcomeAssuranceReadState.UNAVAILABLE:
                if (
                    not source_states
                    or OutcomeAssuranceSourceState.UNAVAILABLE not in source_states
                ):
                    raise ValueError(
                        "unavailable Outcome Assurance projection requires unavailable source state"
                    )
        return self


__all__ = [
    "OutcomeAssuranceAttribution",
    "OutcomeAssuranceAttributionState",
    "OutcomeAssuranceConfidenceInterval",
    "OutcomeAssuranceControlSummary",
    "OutcomeAssuranceGuardEvaluation",
    "OutcomeAssuranceGuardState",
    "OutcomeAssuranceMetric",
    "OutcomeAssuranceMetricState",
    "OutcomeAssuranceProjection",
    "OutcomeAssuranceProvenance",
    "OutcomeAssuranceReadState",
    "OutcomeAssuranceReadiness",
    "OutcomeAssuranceReadinessFacet",
    "OutcomeAssuranceReadinessState",
    "OutcomeAssuranceScope",
    "OutcomeAssuranceSource",
    "OutcomeAssuranceSourceState",
    "OutcomeAssuranceUnavailableReason",
    "OutcomeAssuranceVertical",
    "OutcomeAssuranceWindow",
]
