"""Pure shadow-only Lifecycle Plan admission and constraint checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
)
from fdai_deployment_cli.runtime_release import (
    RecallRecord,
    ReleaseDecision,
    RuntimeRelease,
    evaluate_recall_candidate,
    validate_schema_transition,
)

CapabilityMode = Literal["shadow", "enforce"]
SchemaDirection = Literal["upgrade", "rollback"]
PlanType = Literal["install", "upgrade", "configuration-change", "recall-rolloff", "rollback"]
SignatureVerifier = Callable[[str, bytes, bytes], bool]

_MODE_ORDER: Mapping[CapabilityMode, int] = {"shadow": 0, "enforce": 1}


@dataclass(frozen=True, slots=True)
class LifecycleEffectEnvelope:
    """Maximum effect surface a Plan may use; a Hub Plan can only narrow it."""

    entity_ids: frozenset[str]
    regions: frozenset[str]
    capability_modes: Mapping[str, CapabilityMode]
    destructive_allowed: bool
    max_duration_minutes: int

    def __post_init__(self) -> None:
        if not isinstance(self.destructive_allowed, bool):
            raise TypeError("destructive_allowed MUST be a boolean")
        if (
            isinstance(self.max_duration_minutes, bool)
            or not isinstance(self.max_duration_minutes, int)
            or self.max_duration_minutes < 1
        ):
            raise ValueError("max_duration_minutes MUST be positive")
        for mode in self.capability_modes.values():
            if mode not in _MODE_ORDER:
                raise ValueError("capability mode is unsupported")

    def narrowed_by(self, maximum: LifecycleEffectEnvelope) -> bool:
        """Return whether this envelope is equal to or narrower than the local maximum."""

        if not self.entity_ids <= maximum.entity_ids:
            return False
        if not self.regions <= maximum.regions:
            return False
        if self.destructive_allowed and not maximum.destructive_allowed:
            return False
        if self.max_duration_minutes > maximum.max_duration_minutes:
            return False
        for capability, requested_mode in self.capability_modes.items():
            maximum_mode = maximum.capability_modes.get(capability)
            if maximum_mode is None or _MODE_ORDER[requested_mode] > _MODE_ORDER[maximum_mode]:
                return False
        return True


@dataclass(frozen=True, slots=True)
class LifecyclePlan:
    """Parsed Plan fields relevant to local shadow-only admission."""

    plan_id: str
    audience: str
    hub_key_epoch: int
    hub_key_id: str
    source_state_digest: str
    sequence: int
    fencing_generation: int
    envelope: LifecycleEffectEnvelope
    signed_payload: bytes
    signature: bytes


@dataclass(frozen=True, slots=True)
class PlanAdmissionState:
    """Durable local state used to reject replayed or cross-installation Plans."""

    expected_audience: str
    expected_source_state_digest: str
    last_accepted_sequence: int
    current_fencing_generation: int
    active_hub_key_ids: frozenset[str]
    revoked_hub_key_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class PlanAdmissionDecision:
    """Typed allow or deny result for Plan admission."""

    allowed: bool
    reason_code: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactRequirement:
    """One artifact digest required inside the installation boundary."""

    name: str
    digest: str


@dataclass(frozen=True, slots=True)
class DataResidencyRequirement:
    """Allowed and proposed processing regions for a candidate Plan."""

    allowed_regions: frozenset[str]
    release_regions: frozenset[str]


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    """A UTC maintenance window opened by customer configuration."""

    starts_at: datetime
    ends_at: datetime
    allows_downtime: bool


@dataclass(frozen=True, slots=True)
class SuppressionWindow:
    """A UTC suppression window for an installation, entity, or plan type."""

    scope: str
    starts_at: datetime
    ends_at: datetime
    allows_rollback: bool = False


@dataclass(frozen=True, slots=True)
class LifecycleConstraintContext:
    """Candidate Plan facts and local evidence for pure constraint evaluation."""

    now: datetime
    plan_type: PlanType
    declared_duration_minutes: int
    requires_downtime: bool
    target_release_version: str
    candidate_release: RuntimeRelease
    current_schema_revision: int
    schema_direction: SchemaDirection
    version_range: str
    configuration_schema: Mapping[str, object]
    environment_config: Mapping[str, object]
    entity_overrides: tuple[Mapping[str, object], ...]
    required_artifacts: tuple[ArtifactRequirement, ...]
    available_artifact_digests: frozenset[str]
    data_residency: DataResidencyRequirement
    maintenance_windows: tuple[MaintenanceWindow, ...]
    suppression_windows: tuple[SuppressionWindow, ...]
    entity_ids: frozenset[str]
    capability_ids: tuple[str, ...]
    recall_records: tuple[RecallRecord, ...]


@dataclass(frozen=True, slots=True)
class ConstraintBlock:
    """One blocking lifecycle constraint with a stable reason code."""

    reason_code: str
    details: tuple[str, ...] = ()


def evaluate_plan_admission(
    plan: LifecyclePlan,
    *,
    local_state: PlanAdmissionState,
    locally_derived_maximum: LifecycleEffectEnvelope,
    verify_signature: SignatureVerifier,
) -> PlanAdmissionDecision:
    """Admit a signed Plan only when local replay, key, and envelope checks pass."""

    if plan.audience != local_state.expected_audience:
        return _deny("plan_audience_mismatch", plan.audience)
    if plan.hub_key_id in local_state.revoked_hub_key_ids:
        return _deny("hub_key_revoked", plan.hub_key_id)
    if plan.hub_key_id not in local_state.active_hub_key_ids:
        return _deny("hub_key_not_active", plan.hub_key_id)
    if plan.sequence <= local_state.last_accepted_sequence:
        return _deny("plan_sequence_stale", str(plan.sequence))
    if plan.fencing_generation != local_state.current_fencing_generation:
        return _deny("plan_fencing_generation_mismatch", str(plan.fencing_generation))
    if plan.source_state_digest != local_state.expected_source_state_digest:
        return _deny("plan_source_state_stale", plan.source_state_digest)
    if not plan.envelope.narrowed_by(locally_derived_maximum):
        return _deny("plan_envelope_exceeds_local_maximum", plan.plan_id)
    if not plan.signed_payload or not plan.signature:
        return _deny("plan_signature_invalid", plan.plan_id)
    try:
        verified = verify_signature(plan.hub_key_id, plan.signed_payload, plan.signature)
    except (TypeError, ValueError):
        return _deny("plan_signature_invalid", plan.plan_id)
    if not verified:
        return _deny("plan_signature_invalid", plan.plan_id)
    return PlanAdmissionDecision(True, "allowed")


def evaluate_lifecycle_constraints(
    context: LifecycleConstraintContext,
) -> tuple[ConstraintBlock, ...]:
    """Return every blocking constraint for a candidate Plan without side effects."""

    blocks: list[ConstraintBlock] = []
    _append_if_blocked(blocks, _maintenance_decision(context))
    _append_if_blocked(blocks, _suppression_decision(context))
    version_range_block = _version_range_block(
        context.target_release_version, context.version_range
    )
    if version_range_block is not None:
        blocks.append(version_range_block)
    _append_if_blocked(
        blocks,
        validate_schema_transition(
            current_schema_revision=context.current_schema_revision,
            candidate=context.candidate_release,
            direction=context.schema_direction,
        ),
    )
    missing = tuple(
        artifact.name
        for artifact in context.required_artifacts
        if artifact.digest not in context.available_artifact_digests
    )
    if missing:
        blocks.append(ConstraintBlock("artifact_unavailable", missing))
    override_block = _override_coverage_block(context)
    if override_block is not None:
        blocks.append(override_block)
    if not context.data_residency.release_regions <= context.data_residency.allowed_regions:
        blocks.append(
            ConstraintBlock(
                "data_residency_mismatch",
                tuple(sorted(context.data_residency.release_regions)),
            )
        )
    _append_if_blocked(
        blocks,
        evaluate_recall_candidate(
            release_id=context.target_release_version,
            capability_ids=context.capability_ids,
            recall_records=context.recall_records,
        ),
    )
    return tuple(blocks)


def _maintenance_decision(context: LifecycleConstraintContext) -> ReleaseDecision:
    if context.declared_duration_minutes < 1:
        return ReleaseDecision(False, "maintenance_window_unavailable")
    for window in context.maintenance_windows:
        if not window.starts_at <= context.now < window.ends_at:
            continue
        if context.requires_downtime and not window.allows_downtime:
            continue
        remaining_seconds = (window.ends_at - context.now).total_seconds()
        if remaining_seconds >= context.declared_duration_minutes * 60:
            return ReleaseDecision(True, "allowed")
    return ReleaseDecision(False, "maintenance_window_unavailable")


def _suppression_decision(context: LifecycleConstraintContext) -> ReleaseDecision:
    for window in context.suppression_windows:
        if not window.starts_at <= context.now < window.ends_at:
            continue
        if window.allows_rollback and context.plan_type in {"rollback", "recall-rolloff"}:
            continue
        if window.scope == "installation":
            return ReleaseDecision(False, "suppression_window_active", (window.scope,))
        if window.scope == f"plan:{context.plan_type}":
            return ReleaseDecision(False, "suppression_window_active", (window.scope,))
        for entity_id in context.entity_ids:
            if window.scope == f"entity:{entity_id}":
                return ReleaseDecision(False, "suppression_window_active", (window.scope,))
    return ReleaseDecision(True, "allowed")


def _version_range_block(release_version: str, version_range: str) -> ConstraintBlock | None:
    try:
        resolve_configuration_layers(
            release_version=release_version,
            configuration_schema=_version_range_schema(),
            environment_config={},
            entity_overrides=({"versions": version_range, "values": {"eligible": True}},),
        )
    except ConfigurationValidationError as error:
        if error.code == "missing_matching_override_block":
            return ConstraintBlock("release_version_outside_range", (version_range,))
        return ConstraintBlock(_configuration_reason_code(error), error.path)
    return None


def _override_coverage_block(context: LifecycleConstraintContext) -> ConstraintBlock | None:
    try:
        resolve_configuration_layers(
            release_version=context.target_release_version,
            configuration_schema=context.configuration_schema,
            environment_config=context.environment_config,
            entity_overrides=context.entity_overrides,
        )
    except ConfigurationValidationError as error:
        if error.code == "missing_matching_override_block":
            return ConstraintBlock("override_coverage_missing", error.path)
        return ConstraintBlock(_configuration_reason_code(error), error.path)
    return None


def _configuration_reason_code(error: ConfigurationValidationError) -> str:
    if error.code == "invalid_version_range":
        return "version_range_invalid"
    if error.code == "invalid_release_version":
        return "release_version_invalid"
    return f"configuration_{error.code}"


def _version_range_schema() -> Mapping[str, object]:
    return {
        "eligible": {
            "default": False,
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        }
    }


def _append_if_blocked(blocks: list[ConstraintBlock], decision: ReleaseDecision) -> None:
    if not decision.allowed:
        blocks.append(ConstraintBlock(decision.reason_code, decision.details))


def _deny(reason_code: str, *details: str) -> PlanAdmissionDecision:
    return PlanAdmissionDecision(False, reason_code, tuple(details))
