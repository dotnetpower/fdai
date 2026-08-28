"""Authority-neutral contracts for Cost Governance decisions and settlement."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Protocol

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_MAX_REFS = 64


def _text(name: str, value: str) -> None:
    if not value or len(value) > 512:
        raise ValueError(f"{name} MUST be non-empty and bounded")


def _identifier(name: str, value: str) -> None:
    if len(value) > 256 or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical identifier")


def _digest(name: str, value: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a SHA-256 digest")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _refs(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(values))
    if not 1 <= len(normalized) <= _MAX_REFS:
        raise ValueError(f"{name} MUST contain 1..{_MAX_REFS} unique references")
    for value in normalized:
        _text(name, value)
    return normalized


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


class CostDecisionOutcome(StrEnum):
    """Distinct pending and terminal episode outcomes."""

    NO_OP = "no-op"
    DENY = "deny"
    HOLD = "hold"
    APPROVAL = "approval"
    EXECUTE = "execute"
    ROLLBACK = "rollback"


class CostRecoveryStep(StrEnum):
    """The fixed bounded recovery order."""

    REACQUIRE_CONTEXT = "reacquire-context"
    INDEPENDENT_SOURCE = "independent-source"
    REMOVE_UNSAFE_OPTIONS = "remove-unsafe-options"
    REDUCE_SCOPE = "reduce-scope"
    SELECT_SAFE_OPTION = "select-safe-option"
    BOUNDED_HOLD = "bounded-hold"
    RESIDUAL_APPROVAL = "residual-approval"


COST_RECOVERY_ORDER = tuple(CostRecoveryStep)


class CostRecoveryAttemptStatus(StrEnum):
    """Bounded result of one recovery step."""

    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CONFLICT = "conflict"
    EXHAUSTED = "exhausted"


class CostAutonomyCeiling(IntEnum):
    """A monotonic ceiling that can only stay level or decrease."""

    OBSERVATION = 0
    APPROVAL = 1
    EXECUTION_ELIGIBLE = 2


@dataclass(frozen=True, slots=True)
class CostTargetScope:
    """Bounded target and impact dimensions used to detect widening."""

    target_refs: tuple[str, ...]
    duration_seconds: int
    capacity_delta: Decimal
    impact_units: int

    def __post_init__(self) -> None:
        targets = tuple(sorted(set(self.target_refs)))
        if not targets or len(targets) > 256:
            raise ValueError("cost target scope MUST contain 1..256 unique targets")
        for target in targets:
            _text("target_ref", target)
        if self.duration_seconds < 0 or self.impact_units < 0:
            raise ValueError("cost target duration and impact MUST be nonnegative")
        object.__setattr__(self, "target_refs", targets)

    def does_not_widen(self, previous: CostTargetScope) -> bool:
        """Return true when every scope dimension is unchanged or smaller."""

        return (
            set(self.target_refs) <= set(previous.target_refs)
            and self.duration_seconds <= previous.duration_seconds
            and abs(self.capacity_delta) <= abs(previous.capacity_delta)
            and self.impact_units <= previous.impact_units
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "capacity_delta": str(self.capacity_delta),
            "duration_seconds": self.duration_seconds,
            "impact_units": self.impact_units,
            "target_refs": list(self.target_refs),
        }


@dataclass(frozen=True, slots=True)
class CostActionOption:
    """One bounded option; safety facts are evidence, never permission."""

    option_id: str
    action_type_id: str | None
    scope: CostTargetScope
    unsafe_reasons: tuple[str, ...]
    reversible: bool
    safeguards_complete: bool
    no_action: bool = False
    policy_requires_approval: bool = False
    irreversible: bool = False

    def __post_init__(self) -> None:
        _identifier("option_id", self.option_id)
        if self.action_type_id is not None:
            _identifier("action_type_id", self.action_type_id)
        reasons = tuple(sorted(set(self.unsafe_reasons)))
        if len(reasons) > 32:
            raise ValueError("cost option unsafe reasons MUST be bounded")
        for reason in reasons:
            _identifier("unsafe_reason", reason)
        if self.no_action and self.action_type_id is not None:
            raise ValueError("no-action option MUST NOT cite an ActionType")
        if not self.no_action and self.action_type_id is None:
            raise ValueError("change option MUST cite an ActionType")
        if self.irreversible and self.reversible:
            raise ValueError("irreversible option MUST NOT claim reversibility")
        object.__setattr__(self, "unsafe_reasons", reasons)

    @property
    def safe(self) -> bool:
        return (
            not self.unsafe_reasons
            and (self.no_action or self.safeguards_complete)
            and (self.no_action or self.reversible or self.irreversible)
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "action_type_id": self.action_type_id,
            "irreversible": self.irreversible,
            "no_action": self.no_action,
            "option_id": self.option_id,
            "policy_requires_approval": self.policy_requires_approval,
            "reversible": self.reversible,
            "safeguards_complete": self.safeguards_complete,
            "scope": self.scope.to_mapping(),
            "unsafe_reasons": list(self.unsafe_reasons),
        }


@dataclass(frozen=True, slots=True)
class CostDecisionFrame:
    """Immutable exact-release context evaluated by Forseti-owned judgment."""

    episode_id: str
    package_id: str
    ontology_release_digest: str
    semantic_profile_digest: str
    evidence_cutoff: datetime
    scope: CostTargetScope
    options: tuple[CostActionOption, ...]
    selected_option_id: str | None
    unresolved_facts: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    policy_denied: bool = False
    residual_risk: bool = False
    rollback_required: bool = False

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        _identifier("package_id", self.package_id)
        _digest("ontology_release_digest", self.ontology_release_digest)
        _digest("semantic_profile_digest", self.semantic_profile_digest)
        _aware("evidence_cutoff", self.evidence_cutoff)
        option_ids = tuple(option.option_id for option in self.options)
        if not self.options or len(option_ids) != len(set(option_ids)):
            raise ValueError("decision frame options MUST be non-empty and unique")
        if any(not option.scope.does_not_widen(self.scope) for option in self.options):
            raise ValueError("decision frame option scope MUST stay within the frame scope")
        if self.selected_option_id is not None and self.selected_option_id not in option_ids:
            raise ValueError("selected option MUST exist in the decision frame")
        unresolved = tuple(sorted(set(self.unresolved_facts)))
        for reason in unresolved:
            _identifier("unresolved_fact", reason)
        object.__setattr__(self, "unresolved_facts", unresolved)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs))

    @property
    def digest(self) -> str:
        """Return a deterministic digest of the complete decision frame."""

        return _canonical_digest(self.to_mapping())

    @property
    def selected_option(self) -> CostActionOption | None:
        return next(
            (option for option in self.options if option.option_id == self.selected_option_id),
            None,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "episode_id": self.episode_id,
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
            "evidence_refs": list(self.evidence_refs),
            "ontology_release_digest": self.ontology_release_digest,
            "options": [option.to_mapping() for option in self.options],
            "package_id": self.package_id,
            "policy_denied": self.policy_denied,
            "residual_risk": self.residual_risk,
            "rollback_required": self.rollback_required,
            "scope": self.scope.to_mapping(),
            "selected_option_id": self.selected_option_id,
            "semantic_profile_digest": self.semantic_profile_digest,
            "unresolved_facts": list(self.unresolved_facts),
        }


@dataclass(frozen=True, slots=True)
class CostRecoveryAttempt:
    """One typed recovery response in the fixed order."""

    step: CostRecoveryStep
    status: CostRecoveryAttemptStatus
    hypothesis_id: str
    input_frame_digest: str
    autonomy_ceiling: CostAutonomyCeiling
    evidence_refs: tuple[str, ...]
    attempted_at: datetime
    output_frame: CostDecisionFrame | None = None
    independent_source_authority: str | None = None

    def __post_init__(self) -> None:
        _identifier("hypothesis_id", self.hypothesis_id)
        _digest("input_frame_digest", self.input_frame_digest)
        _aware("attempted_at", self.attempted_at)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs))
        if (self.status is CostRecoveryAttemptStatus.SUCCESS) != (self.output_frame is not None):
            raise ValueError("only a successful recovery attempt MUST carry an output frame")
        has_independent_source = self.independent_source_authority is not None
        requires_independent_source = (
            self.step is CostRecoveryStep.INDEPENDENT_SOURCE
            and self.status is CostRecoveryAttemptStatus.SUCCESS
        )
        if has_independent_source != requires_independent_source:
            raise ValueError(
                "only successful independent-source recovery MUST cite its source authority"
            )
        if self.independent_source_authority is not None:
            _text("independent_source_authority", self.independent_source_authority)


@dataclass(frozen=True, slots=True)
class CostDependencySnapshot:
    """Health evidence for existing accountable agents."""

    saga_available: bool
    vidar_available: bool
    forseti_available: bool
    heimdall_available: bool
    var_available: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _aware("dependency observed_at", self.observed_at)


@dataclass(frozen=True, slots=True)
class CostCoordinationRequest:
    """One bounded decision request assembled from typed event evidence."""

    frame: CostDecisionFrame
    attempts: tuple[CostRecoveryAttempt, ...]
    dependencies: CostDependencySnapshot
    initial_ceiling: CostAutonomyCeiling
    hold_deadline: datetime
    saga_intent_audit_digest: str | None = None
    terminal_audit_digest: str | None = None
    approval_granted: bool | None = None
    approval_receipt_digest: str | None = None

    def __post_init__(self) -> None:
        _aware("hold_deadline", self.hold_deadline)
        if self.hold_deadline <= self.frame.evidence_cutoff:
            raise ValueError("hold deadline MUST follow the decision evidence cutoff")
        for name, value in (
            ("saga_intent_audit_digest", self.saga_intent_audit_digest),
            ("terminal_audit_digest", self.terminal_audit_digest),
            ("approval_receipt_digest", self.approval_receipt_digest),
        ):
            if value is not None:
                _digest(name, value)
        if (self.approval_granted is None) != (self.approval_receipt_digest is None):
            raise ValueError("approval result and receipt MUST be supplied together")


@dataclass(frozen=True, slots=True)
class CostDecisionRecord:
    """Coordinator output for an accountable agent to publish or audit."""

    episode_id: str
    outcome: CostDecisionOutcome
    reason: str
    decision_frame_digest: str
    terminal: bool
    observation_mode: bool
    selected_option_id: str | None
    hold_deadline: datetime | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        _identifier("decision reason", self.reason)
        _digest("decision_frame_digest", self.decision_frame_digest)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs))
        if self.hold_deadline is not None:
            _aware("hold_deadline", self.hold_deadline)
        if self.terminal and self.outcome in {
            CostDecisionOutcome.HOLD,
            CostDecisionOutcome.APPROVAL,
            CostDecisionOutcome.EXECUTE,
            CostDecisionOutcome.ROLLBACK,
        }:
            raise ValueError("pending outcome MUST NOT be terminal")


class CostEffectKind(StrEnum):
    COST = "cost"
    CAPACITY = "capacity"
    SERVICE = "service"
    RECOVERY = "recovery"


class CostSettlementStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    CENSORED = "censored"
    UNSCORABLE = "unscorable"


class CostObservationLane(StrEnum):
    INDEPENDENT = "independent"
    EXECUTION = "execution"


@dataclass(frozen=True, slots=True)
class CostExpectedEffect:
    """One pre-effect expectation with a bounded observation window."""

    effect_id: str
    kind: CostEffectKind
    target_ref: str
    metric: str
    baseline_value: Decimal
    acceptable_min: Decimal
    acceptable_max: Decimal
    predicted_at: datetime
    horizon: timedelta
    telemetry_grace: timedelta
    source_digest: str
    estimated_only: bool = False

    def __post_init__(self) -> None:
        _identifier("effect_id", self.effect_id)
        _text("target_ref", self.target_ref)
        _identifier("metric", self.metric)
        _aware("predicted_at", self.predicted_at)
        _digest("source_digest", self.source_digest)
        if self.acceptable_min > self.acceptable_max:
            raise ValueError("effect acceptable range MUST be ordered")
        if self.horizon <= timedelta(0) or self.telemetry_grace < timedelta(0):
            raise ValueError("effect horizon MUST be positive and grace nonnegative")

    @property
    def horizon_ends_at(self) -> datetime:
        return self.predicted_at + self.horizon

    @property
    def deadline_at(self) -> datetime:
        return self.horizon_ends_at + self.telemetry_grace


@dataclass(frozen=True, slots=True)
class CostCompletenessReceipt:
    effect_id: str
    receipt_digest: str
    complete: bool
    coverage_through_at: datetime
    lane: CostObservationLane
    source_authority: str

    def __post_init__(self) -> None:
        _identifier("effect_id", self.effect_id)
        _digest("receipt_digest", self.receipt_digest)
        _aware("coverage_through_at", self.coverage_through_at)
        _text("source_authority", self.source_authority)


@dataclass(frozen=True, slots=True)
class CostEffectObservation:
    """Observed effect whose source lane cannot be execution output."""

    observation_id: str
    effect_id: str
    target_ref: str
    metric: str
    value: Decimal
    observed_at: datetime
    lane: CostObservationLane
    source_authority: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _identifier("observation_id", self.observation_id)
        _identifier("effect_id", self.effect_id)
        _text("target_ref", self.target_ref)
        _identifier("metric", self.metric)
        _aware("observed_at", self.observed_at)
        _text("source_authority", self.source_authority)
        _digest("evidence_digest", self.evidence_digest)


@dataclass(frozen=True, slots=True)
class CostInterventionObservation:
    """An independently sourced action that censors an effect window."""

    intervention_id: str
    target_ref: str
    effective_at: datetime
    source_authority: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _identifier("intervention_id", self.intervention_id)
        _text("target_ref", self.target_ref)
        _aware("intervention effective_at", self.effective_at)
        _text("source_authority", self.source_authority)
        _digest("evidence_digest", self.evidence_digest)


@dataclass(frozen=True, slots=True)
class CostEffectSettlement:
    effect_id: str
    kind: CostEffectKind
    status: CostSettlementStatus
    reason: str
    terminal: bool
    observed_value: Decimal | None
    observation_digest: str | None
    completeness_digest: str | None
    settled_at: datetime

    def __post_init__(self) -> None:
        _identifier("effect_id", self.effect_id)
        _identifier("settlement reason", self.reason)
        _aware("settled_at", self.settled_at)
        for name, value in (
            ("observation_digest", self.observation_digest),
            ("completeness_digest", self.completeness_digest),
        ):
            if value is not None:
                _digest(name, value)
        if self.status in {CostSettlementStatus.VERIFIED, CostSettlementStatus.FAILED} and (
            self.observed_value is None
            or self.observation_digest is None
            or self.completeness_digest is None
        ):
            raise ValueError("scored settlement requires observation and completeness evidence")


@dataclass(frozen=True, slots=True)
class CostPostRecoveryObservation:
    recovery_request_id: str
    observed_at: datetime
    restored: bool
    complete: bool
    lane: CostObservationLane
    source_authority: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _identifier("recovery_request_id", self.recovery_request_id)
        _aware("recovery observed_at", self.observed_at)
        _text("source_authority", self.source_authority)
        _digest("evidence_digest", self.evidence_digest)


@dataclass(frozen=True, slots=True)
class CostRollbackRequest:
    """Typed stop-condition and rollback request for Vidar-owned handling."""

    request_id: str
    episode_id: str
    decision_frame_digest: str
    failed_effect_ids: tuple[str, ...]
    stop_requested: bool
    rollback_requested: bool
    reason: str
    requested_at: datetime
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier("request_id", self.request_id)
        _identifier("episode_id", self.episode_id)
        _digest("decision_frame_digest", self.decision_frame_digest)
        effects = tuple(sorted(set(self.failed_effect_ids)))
        if not effects:
            raise ValueError("rollback request MUST cite failed effects")
        for effect_id in effects:
            _identifier("failed_effect_id", effect_id)
        _identifier("rollback reason", self.reason)
        _aware("requested_at", self.requested_at)
        object.__setattr__(self, "failed_effect_ids", effects)
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs))


@dataclass(frozen=True, slots=True)
class CostEpisodeSettlement:
    """Complete multi-effect result; realized savings require independent verification."""

    episode_id: str
    decision_frame_digest: str
    effects: tuple[CostEffectSettlement, ...]
    terminal: bool
    realized_savings: Decimal
    rollback_request: CostRollbackRequest | None
    recovery_observed: bool
    settled_at: datetime

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        _digest("decision_frame_digest", self.decision_frame_digest)
        effect_ids = tuple(item.effect_id for item in self.effects)
        if not effects_or_unique(effect_ids):
            raise ValueError("episode settlement effects MUST be non-empty and unique")
        _aware("settled_at", self.settled_at)
        if self.realized_savings < 0:
            raise ValueError("realized savings MUST be nonnegative")
        if self.rollback_request is not None and self.realized_savings != 0:
            raise ValueError("rollback settlement MUST NOT report realized savings")
        if self.terminal and not all(item.terminal for item in self.effects):
            raise ValueError("terminal settlement requires every effect to be terminal")


def effects_or_unique(effect_ids: tuple[str, ...]) -> bool:
    return bool(effect_ids) and len(effect_ids) == len(set(effect_ids))


@dataclass(frozen=True, slots=True)
class CostCaseProjection:
    """Immutable replay input for Muninn; it has no write or action methods."""

    episode_id: str
    revision: int
    decision: CostDecisionRecord
    settlement: CostEpisodeSettlement | None
    recovery_attempts: tuple[CostRecoveryAttempt, ...]
    evidence_refs: tuple[str, ...]
    terminal_audit_digest: str | None
    lineage_complete: bool
    projection_digest: str

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        if self.revision < 1:
            raise ValueError("case projection revision MUST be positive")
        if self.decision.episode_id != self.episode_id:
            raise ValueError("case projection decision episode MUST match")
        if self.settlement is not None and self.settlement.episode_id != self.episode_id:
            raise ValueError("case projection settlement episode MUST match")
        object.__setattr__(self, "evidence_refs", _refs("evidence_refs", self.evidence_refs))
        if self.terminal_audit_digest is not None:
            _digest("terminal_audit_digest", self.terminal_audit_digest)
        if self.lineage_complete and self.terminal_audit_digest is None:
            raise ValueError("complete case lineage requires a Saga terminal audit")
        _digest("projection_digest", self.projection_digest)


@dataclass(frozen=True, slots=True)
class CostLearningCohortInput:
    """Inert balanced exact-case input for Norns-owned candidate analysis."""

    cohort_id: str
    case_refs: tuple[str, ...]
    positive_count: int
    negative_count: int
    lineage_digest: str
    inert: bool = True

    def __post_init__(self) -> None:
        _identifier("cohort_id", self.cohort_id)
        refs = tuple(sorted(set(self.case_refs)))
        if len(refs) != self.positive_count + self.negative_count:
            raise ValueError("learning cohort counts MUST match unique case references")
        if self.positive_count < 1 or self.negative_count < 1:
            raise ValueError("learning cohort MUST include positive and negative outcomes")
        if not self.inert:
            raise ValueError("learning cohort input MUST remain inert")
        _digest("lineage_digest", self.lineage_digest)
        object.__setattr__(self, "case_refs", refs)


@dataclass(frozen=True, slots=True)
class CostEpisodePersistenceRecord:
    """Revisioned retained episode metadata for a Core-owned store."""

    episode_id: str
    revision: int
    idempotency_key: str
    outcome: CostDecisionOutcome
    reason: str
    decision_frame_digest: str
    terminal: bool
    recorded_at: datetime
    retention_until: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None
    purged_at: datetime | None = None

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        if self.revision < 1:
            raise ValueError("episode persistence revision MUST be positive")
        _text("idempotency_key", self.idempotency_key)
        _identifier("reason", self.reason)
        _digest("decision_frame_digest", self.decision_frame_digest)
        _aware("recorded_at", self.recorded_at)
        _aware("retention_until", self.retention_until)
        if self.retention_until <= self.recorded_at:
            raise ValueError("episode retention MUST follow recording")
        if self.legal_hold != (self.legal_hold_ref is not None):
            raise ValueError("legal hold state and reference MUST be supplied together")
        if self.purged_at is not None:
            _aware("purged_at", self.purged_at)


@dataclass(frozen=True, slots=True)
class CostEvidenceRecord:
    """Append-only attributed evidence for one episode revision."""

    episode_id: str
    episode_revision: int
    evidence_sequence: int
    evidence_ref: str
    evidence_digest: str
    source_authority: str
    recorded_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        if self.episode_revision < 1 or self.evidence_sequence < 0:
            raise ValueError("cost evidence revision and sequence MUST be valid")
        _text("evidence_ref", self.evidence_ref)
        _digest("evidence_digest", self.evidence_digest)
        _text("source_authority", self.source_authority)
        _aware("recorded_at", self.recorded_at)
        _text("idempotency_key", self.idempotency_key)


class CostGovernanceEpisodeStore(Protocol):
    """Append episode evidence and CAS retention without package activation coupling."""

    async def append_cost_episode(
        self,
        record: CostEpisodePersistenceRecord,
        *,
        expected_revision: int,
    ) -> bool: ...

    async def append_cost_recovery_attempt(
        self,
        episode_id: str,
        attempt_index: int,
        attempt: CostRecoveryAttempt,
    ) -> bool: ...

    async def append_cost_settlement(self, settlement: CostEpisodeSettlement) -> bool: ...

    async def append_cost_evidence(self, record: CostEvidenceRecord) -> bool: ...

    async def read_cost_episode(
        self,
        episode_id: str,
    ) -> CostEpisodePersistenceRecord | None: ...

    async def compare_and_set_cost_retention(
        self,
        episode_id: str,
        *,
        expected_revision: int,
        legal_hold: bool,
        legal_hold_ref: str | None,
        recorded_at: datetime,
    ) -> bool: ...

    async def purge_due_cost_episodes(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[str, ...]: ...


__all__ = [
    "COST_RECOVERY_ORDER",
    "CostActionOption",
    "CostAutonomyCeiling",
    "CostCaseProjection",
    "CostCompletenessReceipt",
    "CostCoordinationRequest",
    "CostDecisionFrame",
    "CostDecisionOutcome",
    "CostDecisionRecord",
    "CostDependencySnapshot",
    "CostEffectKind",
    "CostEffectObservation",
    "CostEffectSettlement",
    "CostEvidenceRecord",
    "CostEpisodePersistenceRecord",
    "CostEpisodeSettlement",
    "CostExpectedEffect",
    "CostGovernanceEpisodeStore",
    "CostInterventionObservation",
    "CostLearningCohortInput",
    "CostObservationLane",
    "CostPostRecoveryObservation",
    "CostRecoveryAttempt",
    "CostRecoveryAttemptStatus",
    "CostRecoveryStep",
    "CostRollbackRequest",
    "CostSettlementStatus",
    "CostTargetScope",
]
