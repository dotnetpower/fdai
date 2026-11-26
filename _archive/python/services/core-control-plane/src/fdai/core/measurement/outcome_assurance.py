"""Typed read-model contract for the Outcome Assurance projection."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from fdai.shared.contracts.models import ContractBase

NonEmpty = Annotated[str, Field(min_length=1)]
EvidenceRefs = Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=32)]


class OutcomeVertical(StrEnum):
    RESILIENCE = "resilience"
    CHANGE_SAFETY = "change_safety"
    COST_GOVERNANCE = "cost_governance"


class ReadinessFacet(StrEnum):
    PLATFORM = "platform"
    EVIDENCE = "evidence"
    DETECTION = "detection"
    ACTION_SAFETY = "action_safety"
    OPERATIONAL_HANDOFF = "operational_handoff"
    MEASUREMENT = "measurement"
    PROMOTION = "promotion"


class ReadinessFacetState(StrEnum):
    UNKNOWN = "unknown"
    BLOCKED = "blocked"
    OBSERVED = "observed"
    READY = "ready"


class ObjectiveAttributionState(StrEnum):
    UNATTRIBUTED = "unattributed"
    PARTIAL = "partial"
    ATTRIBUTED = "attributed"


class OutcomeEvidenceState(StrEnum):
    NOT_CONNECTED = "not_connected"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    MEASURED = "measured"
    REGRESSED = "regressed"


class ControlAssuranceState(StrEnum):
    UNKNOWN = "unknown"
    BLOCKED = "blocked"
    ATTENTION = "attention"
    HEALTHY = "healthy"


class OutcomeAssuranceScope(ContractBase):
    """Pinned scope identity for one read-only projection."""

    scope_ref: NonEmpty
    service_refs: tuple[NonEmpty, ...] = ()
    workload_refs: tuple[NonEmpty, ...] = ()
    vertical: OutcomeVertical | None = None

    @field_validator("service_refs", "workload_refs")
    @classmethod
    def require_unique_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Outcome Assurance scope refs MUST be unique")
        return value


class OutcomeAssuranceWindow(ContractBase):
    """Measurement window identity shared by all projection groups."""

    start: datetime
    end: datetime
    scenario_set_version: NonEmpty

    @field_validator("start", "end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance window timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> OutcomeAssuranceWindow:
        if self.end <= self.start:
            raise ValueError("Outcome Assurance window end MUST follow start")
        return self


class ReadinessFacetSnapshot(ContractBase):
    """Freshness-bound state for one existing readiness owner."""

    facet: ReadinessFacet
    state: ReadinessFacetState
    evidence_refs: tuple[NonEmpty, ...] = ()
    observed_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("readiness freshness timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> ReadinessFacetSnapshot:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("readiness evidence refs MUST be unique")
        if (self.observed_at is None) != (self.expires_at is None):
            raise ValueError("readiness freshness requires both observed_at and expires_at")
        observed_at = self.observed_at
        expires_at = self.expires_at
        if observed_at is not None and expires_at is not None and expires_at <= observed_at:
            raise ValueError("readiness freshness expiry MUST follow observation time")
        if self.state is ReadinessFacetState.UNKNOWN:
            return self
        if not self.evidence_refs:
            raise ValueError("non-unknown readiness state MUST cite evidence")
        if observed_at is None:
            raise ValueError("non-unknown readiness state MUST include freshness timestamps")
        return self


class FinalizedOutcomeEvent(ContractBase):
    """One finalized denominator event with explicit objective-chain references."""

    event_id: NonEmpty
    finalized_at: datetime
    decision_case_id: NonEmpty | None = None
    protected_objective_ref: NonEmpty | None = None
    workflow_ref: NonEmpty | None = None
    action_type_id: NonEmpty | None = None
    action_run_id: NonEmpty | None = None
    observed_outcome_ref: NonEmpty | None = None
    evidence_refs: EvidenceRefs

    @field_validator("finalized_at")
    @classmethod
    def require_finalized_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("finalized Outcome Assurance event time MUST be timezone-aware")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def require_unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("finalized Outcome Assurance event evidence refs MUST be unique")
        return value


class ObjectiveAttributionSummary(ContractBase):
    """Coverage-preserving attribution summary for finalized events."""

    state: ObjectiveAttributionState
    objective_refs: tuple[NonEmpty, ...] = ()
    workflow_refs: tuple[NonEmpty, ...] = ()
    action_type_ids: tuple[NonEmpty, ...] = ()
    finalized_events: Annotated[int, Field(ge=0)]
    attributed_events: Annotated[int, Field(ge=0)]
    unattributed_events: Annotated[int, Field(ge=0)]
    coverage: Annotated[float, Field(ge=0, le=1)]
    evidence_refs: tuple[NonEmpty, ...] = ()

    @model_validator(mode="after")
    def validate_summary(self) -> ObjectiveAttributionSummary:
        groups = (
            ("objective refs", self.objective_refs),
            ("workflow refs", self.workflow_refs),
            ("action type ids", self.action_type_ids),
            ("evidence refs", self.evidence_refs),
        )
        for label, values in groups:
            if len(values) != len(set(values)):
                raise ValueError(f"objective attribution {label} MUST be unique")
        if self.finalized_events != self.attributed_events + self.unattributed_events:
            raise ValueError("finalized_events MUST equal attributed_events + unattributed_events")
        expected_coverage = (
            0.0 if self.finalized_events == 0 else self.attributed_events / self.finalized_events
        )
        if not math.isclose(self.coverage, expected_coverage, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("objective attribution coverage MUST match the finalized-event ratio")
        expected_state = ObjectiveAttributionState.PARTIAL
        if self.attributed_events == 0:
            expected_state = ObjectiveAttributionState.UNATTRIBUTED
        elif self.unattributed_events == 0:
            expected_state = ObjectiveAttributionState.ATTRIBUTED
        if self.state is not expected_state:
            raise ValueError(
                "objective attribution state MUST reflect attributed and unattributed coverage"
            )
        if self.attributed_events > 0 and not self.evidence_refs:
            raise ValueError("attributed Outcome Assurance events MUST cite evidence")
        if self.attributed_events > 0 and not self.objective_refs:
            raise ValueError("attributed Outcome Assurance events MUST cite objective refs")
        return self


class ConfidenceInterval(ContractBase):
    """Confidence interval for one measured outcome."""

    low: float
    high: float

    @model_validator(mode="after")
    def validate_interval(self) -> ConfidenceInterval:
        if self.high < self.low:
            raise ValueError("confidence interval high MUST be >= low")
        return self


class OutcomeMeasurement(ContractBase):
    """One objective-scoped outcome measure for the projection window."""

    objective_ref: NonEmpty
    metric: NonEmpty
    state: OutcomeEvidenceState
    current_value: float | None = None
    baseline_value: float | None = None
    target_value: float | None = None
    unit: NonEmpty | None = None
    sample_size: Annotated[int | None, Field(ge=1)] = None
    confidence_interval: ConfidenceInterval | None = None
    source_time: datetime | None = None
    evidence_refs: tuple[NonEmpty, ...] = ()

    @field_validator("source_time")
    @classmethod
    def require_source_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("outcome measurement source_time MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_measurement(self) -> OutcomeMeasurement:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("outcome measurement evidence refs MUST be unique")
        if self.state in {OutcomeEvidenceState.MEASURED, OutcomeEvidenceState.REGRESSED}:
            required = (
                self.current_value,
                self.baseline_value,
                self.target_value,
                self.unit,
                self.sample_size,
                self.confidence_interval,
                self.source_time,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "measured Outcome Assurance values MUST include baseline, target, unit, "
                    "sample_size, confidence_interval, and source_time"
                )
            if not self.evidence_refs:
                raise ValueError("measured Outcome Assurance values MUST cite evidence")
        return self


class GuardEvaluation(ContractBase):
    """One guard threshold result carried into the read model."""

    guard_id: NonEmpty
    threshold: float
    observed_value: float
    passed: bool
    evidence_ref: NonEmpty


class ControlAssuranceSummary(ContractBase):
    """Guard and policy status without copying execution authority."""

    state: ControlAssuranceState
    guard_evaluations: tuple[GuardEvaluation, ...] = ()
    policy_escape_count: Annotated[int, Field(ge=0)] = 0
    evidence_refs: tuple[NonEmpty, ...] = ()

    @model_validator(mode="after")
    def validate_control_assurance(self) -> ControlAssuranceSummary:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("control assurance evidence refs MUST be unique")
        guard_ids = [item.guard_id for item in self.guard_evaluations]
        if len(guard_ids) != len(set(guard_ids)):
            raise ValueError("guard evaluations MUST be unique by guard_id")
        failed_guards = tuple(item for item in self.guard_evaluations if not item.passed)
        if self.policy_escape_count > 0 and self.state is not ControlAssuranceState.BLOCKED:
            raise ValueError("policy escapes MUST force blocked control assurance")
        if failed_guards and self.state is ControlAssuranceState.HEALTHY:
            raise ValueError("failed guards cannot report healthy control assurance")
        if (
            self.state is ControlAssuranceState.BLOCKED
            and not failed_guards
            and self.policy_escape_count == 0
        ):
            raise ValueError("blocked control assurance MUST cite a failed guard or policy escape")
        if self.state is not ControlAssuranceState.UNKNOWN and not self.evidence_refs:
            raise ValueError("non-unknown control assurance MUST cite evidence")
        return self


class OutcomeProvenance(ContractBase):
    """Pinned source set and as-of time for one projection response."""

    source_names: tuple[NonEmpty, ...]
    as_of: datetime
    synthetic: bool = False

    @field_validator("as_of")
    @classmethod
    def require_as_of_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance provenance MUST be timezone-aware")
        return value

    @field_validator("source_names")
    @classmethod
    def validate_source_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Outcome Assurance provenance MUST list at least one source")
        if len(value) != len(set(value)):
            raise ValueError("Outcome Assurance provenance source names MUST be unique")
        return value


class OutcomeMeasurementObservation(ContractBase):
    """One authoritative event outcome used to resolve retries and corrections."""

    event_id: NonEmpty
    objective_ref: NonEmpty
    metric: NonEmpty
    observation_id: NonEmpty
    observed_at: datetime
    recorded_at: datetime
    value: float
    evidence_ref: NonEmpty

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def require_observation_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Outcome Assurance observation timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_times(self) -> OutcomeMeasurementObservation:
        if self.recorded_at.astimezone(UTC) < self.observed_at.astimezone(UTC):
            raise ValueError(
                "recorded_at MUST be >= observed_at for Outcome Assurance observations"
            )
        return self


class OutcomeAssuranceProjection(ContractBase):
    """Read-only, replay-stable Outcome Assurance response."""

    scope: OutcomeAssuranceScope
    window: OutcomeAssuranceWindow
    readiness: tuple[ReadinessFacetSnapshot, ...]
    alignment: ObjectiveAttributionSummary
    outcomes: tuple[OutcomeMeasurement, ...]
    guards: ControlAssuranceSummary
    provenance: OutcomeProvenance

    @model_validator(mode="after")
    def validate_projection(self) -> OutcomeAssuranceProjection:
        facets = [item.facet for item in self.readiness]
        if len(facets) != len(set(facets)):
            raise ValueError("Outcome Assurance readiness facets MUST be unique")
        outcome_keys = [(item.objective_ref, item.metric) for item in self.outcomes]
        if len(outcome_keys) != len(set(outcome_keys)):
            raise ValueError("Outcome Assurance outcomes MUST be unique by objective_ref + metric")
        return self

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        """Return byte-stable JSON for projection replay and hashing."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> OutcomeAssuranceProjection:
        """Decode a stored projection without weakening contract validation."""
        return cls.model_validate_json(payload)


def latest_authoritative_observations(
    observations: tuple[OutcomeMeasurementObservation, ...],
) -> tuple[OutcomeMeasurementObservation, ...]:
    """Keep the latest authoritative row per event/objective/metric deterministically."""

    winners: dict[tuple[str, str, str], OutcomeMeasurementObservation] = {}
    for observation in observations:
        key = (observation.event_id, observation.objective_ref, observation.metric)
        prior = winners.get(key)
        if prior is None or _observation_order(observation) > _observation_order(prior):
            winners[key] = observation
    return tuple(
        winners[key]
        for key in sorted(
            winners,
            key=lambda item: item,
        )
    )


def summarize_objective_attribution(
    finalized_events: tuple[FinalizedOutcomeEvent, ...],
    observations: tuple[OutcomeMeasurementObservation, ...],
) -> ObjectiveAttributionSummary:
    """Join exact finalized-event chains to their latest authoritative observations."""

    event_ids = [event.event_id for event in finalized_events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("finalized Outcome Assurance events MUST be unique by event_id")
    event_id_set = set(event_ids)
    authoritative = latest_authoritative_observations(observations)
    orphan_event_ids = sorted(
        {observation.event_id for observation in authoritative} - event_id_set
    )
    if orphan_event_ids:
        raise ValueError(
            "Outcome Assurance observations MUST reference a finalized event in the join"
        )

    observations_by_objective: dict[tuple[str, str], list[OutcomeMeasurementObservation]] = {}
    for observation in authoritative:
        observations_by_objective.setdefault(
            (observation.event_id, observation.objective_ref),
            [],
        ).append(observation)

    objective_refs: set[str] = set()
    workflow_refs: set[str] = set()
    action_type_ids: set[str] = set()
    evidence_refs: set[str] = set()
    attributed_events = 0
    for event in finalized_events:
        evidence_refs.update(event.evidence_refs)
        objective_ref = event.protected_objective_ref
        workflow_ref = event.workflow_ref
        action_type_id = event.action_type_id
        if (
            event.decision_case_id is None
            or objective_ref is None
            or workflow_ref is None
            or action_type_id is None
            or event.action_run_id is None
            or event.observed_outcome_ref is None
        ):
            continue
        matched_observations = observations_by_objective.get(
            (event.event_id, objective_ref),
            (),
        )
        if not matched_observations:
            continue
        attributed_events += 1
        objective_refs.add(objective_ref)
        workflow_refs.add(workflow_ref)
        action_type_ids.add(action_type_id)
        evidence_refs.update(item.evidence_ref for item in matched_observations)

    finalized_count = len(finalized_events)
    unattributed_events = finalized_count - attributed_events
    state = ObjectiveAttributionState.PARTIAL
    if attributed_events == 0:
        state = ObjectiveAttributionState.UNATTRIBUTED
    elif unattributed_events == 0:
        state = ObjectiveAttributionState.ATTRIBUTED
    return ObjectiveAttributionSummary(
        state=state,
        objective_refs=tuple(sorted(objective_refs)),
        workflow_refs=tuple(sorted(workflow_refs)),
        action_type_ids=tuple(sorted(action_type_ids)),
        finalized_events=finalized_count,
        attributed_events=attributed_events,
        unattributed_events=unattributed_events,
        coverage=0.0 if finalized_count == 0 else attributed_events / finalized_count,
        evidence_refs=tuple(sorted(evidence_refs)),
    )


def _observation_order(
    observation: OutcomeMeasurementObservation,
) -> tuple[datetime, datetime, str]:
    return (
        observation.recorded_at.astimezone(UTC),
        observation.observed_at.astimezone(UTC),
        observation.observation_id,
    )


__all__ = [
    "ConfidenceInterval",
    "ControlAssuranceState",
    "ControlAssuranceSummary",
    "FinalizedOutcomeEvent",
    "GuardEvaluation",
    "ObjectiveAttributionState",
    "ObjectiveAttributionSummary",
    "OutcomeAssuranceProjection",
    "OutcomeAssuranceScope",
    "OutcomeAssuranceWindow",
    "OutcomeEvidenceState",
    "OutcomeMeasurement",
    "OutcomeMeasurementObservation",
    "OutcomeProvenance",
    "OutcomeVertical",
    "ReadinessFacet",
    "ReadinessFacetSnapshot",
    "ReadinessFacetState",
    "latest_authoritative_observations",
    "summarize_objective_attribution",
]
