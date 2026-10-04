"""Pure shadow-only Lifecycle Plan admission and constraint checks."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fdai_deployment_cli.contracts import canonical_bytes
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
SuppressionOrigin = Literal["manual", "failure"]
SignatureVerifier = Callable[[str, bytes, bytes], bool]

_MODE_ORDER: Mapping[CapabilityMode, int] = {"shadow": 0, "enforce": 1}
_SCOPE_ID = re.compile(r"[a-z][a-z0-9._-]*\Z", re.ASCII)


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
        for capability, mode in self.capability_modes.items():
            if not isinstance(capability, str):
                raise TypeError("capability mode keys MUST be strings")
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
    plan_type: PlanType
    target_release_id: str
    target_release_digest: str
    configuration_revision_digest: str
    entity_ids: frozenset[str]
    rollback_target_plan_id: str | None
    declared_duration_minutes: int
    envelope: LifecycleEffectEnvelope
    expires_at: datetime
    signed_payload: bytes
    signature: bytes

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence MUST be an integer")
        if self.sequence < 0:
            raise ValueError("sequence MUST be non-negative")
        if (
            isinstance(self.declared_duration_minutes, bool)
            or not isinstance(self.declared_duration_minutes, int)
            or self.declared_duration_minutes < 1
        ):
            raise ValueError("declared_duration_minutes MUST be positive")


@dataclass(frozen=True, slots=True)
class PlanAdmissionState:
    """Durable local state used to reject replayed or cross-installation Plans."""

    expected_audience: str
    expected_source_state_digest: str
    last_accepted_sequence: int
    current_hub_key_epoch: int
    current_fencing_generation: int
    active_hub_key_ids: frozenset[str]
    revoked_hub_key_ids: frozenset[str]
    hub_key_epochs: Mapping[str, int]


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

    def __post_init__(self) -> None:
        _require_aware_datetime(self.starts_at, "starts_at")
        _require_aware_datetime(self.ends_at, "ends_at")


@dataclass(frozen=True, slots=True)
class SuppressionWindow:
    """A UTC suppression window for an installation, entity, or plan type."""

    scope: str
    starts_at: datetime
    ends_at: datetime
    origin: SuppressionOrigin = "manual"
    failed_plan_id: str | None = None

    def __post_init__(self) -> None:
        _require_aware_datetime(self.starts_at, "starts_at")
        _require_aware_datetime(self.ends_at, "ends_at")


@dataclass(frozen=True, slots=True)
class LifecycleConstraintContext:
    """Candidate Plan facts and local evidence for pure constraint evaluation."""

    now: datetime
    plan_id: str
    plan_type: PlanType
    rollback_target_plan_id: str | None
    declared_duration_minutes: int
    requires_downtime: bool
    target_release_version: str
    candidate_release: RuntimeRelease
    configuration_revision_digest: str
    current_schema_revision: int
    version_range: str
    configuration_schema: Mapping[str, object]
    environment_config: Mapping[str, object]
    entity_overrides: tuple[Mapping[str, object], ...]
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
    trusted_now: datetime,
) -> PlanAdmissionDecision:
    """Admit a signed Plan only when local replay, key, and envelope checks pass."""

    if not plan.signed_payload or not plan.signature:
        return _deny("plan_signature_invalid", plan.plan_id)
    try:
        verified = verify_signature(plan.hub_key_id, plan.signed_payload, plan.signature)
    except (TypeError, ValueError):
        return _deny("plan_signature_invalid", plan.plan_id)
    if verified is not True:
        return _deny("plan_signature_invalid", plan.plan_id)
    if plan.signed_payload != canonical_plan_payload(plan):
        return _deny("plan_payload_mismatch", plan.plan_id)
    if plan.hub_key_id in local_state.revoked_hub_key_ids:
        return _deny("hub_key_revoked", plan.hub_key_id)
    if plan.hub_key_id not in local_state.active_hub_key_ids:
        return _deny("hub_key_not_active", plan.hub_key_id)
    if plan.hub_key_epoch != local_state.current_hub_key_epoch:
        return _deny("hub_key_epoch_mismatch", str(plan.hub_key_epoch))
    if local_state.hub_key_epochs.get(plan.hub_key_id) != plan.hub_key_epoch:
        return _deny("hub_key_epoch_mismatch", plan.hub_key_id)
    if trusted_now.tzinfo is None or trusted_now.utcoffset() is None:
        return _deny("trusted_clock_timezone_missing")
    if plan.expires_at.tzinfo is None or plan.expires_at.utcoffset() is None:
        return _deny("plan_expiry_timezone_missing", plan.plan_id)
    if plan.expires_at <= trusted_now:
        return _deny("plan_expired", plan.plan_id)
    if plan.audience != local_state.expected_audience:
        return _deny("plan_audience_mismatch", plan.audience)
    if plan.sequence <= local_state.last_accepted_sequence:
        return _deny("plan_sequence_stale", str(plan.sequence))
    if plan.fencing_generation != local_state.current_fencing_generation:
        return _deny("plan_fencing_generation_mismatch", str(plan.fencing_generation))
    if plan.source_state_digest != local_state.expected_source_state_digest:
        return _deny("plan_source_state_stale", plan.source_state_digest)
    if not plan.envelope.narrowed_by(locally_derived_maximum):
        return _deny("plan_envelope_exceeds_local_maximum", plan.plan_id)
    return PlanAdmissionDecision(True, "allowed")


def canonical_plan_payload(plan: LifecyclePlan) -> bytes:
    """Return the byte-for-byte JSON payload the Hub key must sign."""

    return canonical_bytes(
        {
            "audience": plan.audience,
            "envelope": {
                "capability_modes": dict(sorted(plan.envelope.capability_modes.items())),
                "destructive_allowed": plan.envelope.destructive_allowed,
                "entity_ids": sorted(plan.envelope.entity_ids),
                "max_duration_minutes": plan.envelope.max_duration_minutes,
                "regions": sorted(plan.envelope.regions),
            },
            "expires_at": plan.expires_at.isoformat(),
            "fencing_generation": plan.fencing_generation,
            "hub_key_epoch": plan.hub_key_epoch,
            "hub_key_id": plan.hub_key_id,
            "configuration_revision_digest": plan.configuration_revision_digest,
            "declared_duration_minutes": plan.declared_duration_minutes,
            "entity_ids": sorted(plan.entity_ids),
            "plan_id": plan.plan_id,
            "plan_type": plan.plan_type,
            "rollback_target_plan_id": plan.rollback_target_plan_id,
            "sequence": plan.sequence,
            "source_state_digest": plan.source_state_digest,
            "target_release_digest": plan.target_release_digest,
            "target_release_id": plan.target_release_id,
        }
    )


def evaluate_lifecycle_constraints(
    context: LifecycleConstraintContext,
    *,
    admitted_plan: LifecyclePlan,
) -> tuple[ConstraintBlock, ...]:
    """Return every blocking constraint for a candidate Plan without side effects."""

    blocks: list[ConstraintBlock] = []
    context_block = _plan_context_block(context, admitted_plan)
    if context_block is not None:
        blocks.append(context_block)
    if context.candidate_release.digest != admitted_plan.target_release_digest:
        blocks.append(
            ConstraintBlock(
                "target_release_digest_mismatch",
                (context.candidate_release.digest, admitted_plan.target_release_digest),
            )
        )
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
            direction=_schema_direction(context.plan_type),
        ),
    )
    required_artifacts = _required_artifacts(context.candidate_release)
    if not required_artifacts:
        blocks.append(ConstraintBlock("artifact_requirements_missing"))
    else:
        missing = tuple(
            artifact.name
            for artifact in required_artifacts
            if artifact.digest not in context.available_artifact_digests
        )
        if missing:
            blocks.append(ConstraintBlock("artifact_unavailable", missing))
    override_block = _override_coverage_block(context)
    if override_block is not None:
        blocks.append(override_block)
    if not context.data_residency.release_regions:
        blocks.append(ConstraintBlock("data_residency_missing"))
    elif not context.data_residency.release_regions <= context.data_residency.allowed_regions:
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
    requires_downtime = context.requires_downtime or bool(
        context.entity_ids & set(context.candidate_release.downtime_entities)
    )
    for window in context.maintenance_windows:
        if window.starts_at >= window.ends_at:
            return ReleaseDecision(
                False, "maintenance_window_invalid", (window.starts_at.isoformat(),)
            )
        if not window.starts_at <= context.now < window.ends_at:
            continue
        if requires_downtime and not window.allows_downtime:
            continue
        remaining_seconds = (window.ends_at - context.now).total_seconds()
        if remaining_seconds >= context.declared_duration_minutes * 60:
            return ReleaseDecision(True, "allowed")
    return ReleaseDecision(False, "maintenance_window_unavailable")


def _suppression_decision(context: LifecycleConstraintContext) -> ReleaseDecision:
    for window in context.suppression_windows:
        if window.starts_at >= window.ends_at:
            return ReleaseDecision(False, "suppression_window_invalid", (window.scope,))
        if window.origin not in {"manual", "failure"}:
            return ReleaseDecision(False, "suppression_window_invalid", (window.scope,))
        if not window.starts_at <= context.now < window.ends_at:
            continue
        scope_decision = _suppression_scope_decision(window)
        if scope_decision is not None:
            return scope_decision
        if (
            window.origin == "failure"
            and context.plan_type == "rollback"
            and window.failed_plan_id is not None
            and window.failed_plan_id == context.rollback_target_plan_id
        ):
            continue
        if _scope_matches(window.scope, context):
            return ReleaseDecision(False, "suppression_window_active", (window.scope,))
    return ReleaseDecision(True, "allowed")


def _suppression_scope_decision(window: SuppressionWindow) -> ReleaseDecision | None:
    if window.scope == "installation":
        return None
    if window.scope.startswith("plan:"):
        plan_type = window.scope.removeprefix("plan:")
        if plan_type not in {
            "install",
            "upgrade",
            "configuration-change",
            "recall-rolloff",
            "rollback",
        }:
            return ReleaseDecision(False, "suppression_scope_invalid", (window.scope,))
        return None
    if window.scope.startswith("entity:"):
        entity_id = window.scope.removeprefix("entity:")
        if _SCOPE_ID.fullmatch(entity_id) is None:
            return ReleaseDecision(False, "suppression_scope_invalid", (window.scope,))
        return None
    return ReleaseDecision(False, "suppression_scope_invalid", (window.scope,))


def _scope_matches(scope: str, context: LifecycleConstraintContext) -> bool:
    if scope == "installation":
        return True
    if scope == f"plan:{context.plan_type}":
        return True
    return any(scope == f"entity:{entity_id}" for entity_id in context.entity_ids)


def _schema_direction(plan_type: PlanType) -> SchemaDirection:
    if plan_type in {"rollback", "recall-rolloff"}:
        return "rollback"
    return "upgrade"


def _plan_context_block(
    context: LifecycleConstraintContext, plan: LifecyclePlan
) -> ConstraintBlock | None:
    comparisons = (
        ("plan_id", context.plan_id, plan.plan_id),
        ("plan_type", context.plan_type, plan.plan_type),
        ("target_release_version", context.target_release_version, plan.target_release_id),
        (
            "configuration_revision_digest",
            context.configuration_revision_digest,
            plan.configuration_revision_digest,
        ),
        ("entity_ids", context.entity_ids, plan.entity_ids),
        ("rollback_target_plan_id", context.rollback_target_plan_id, plan.rollback_target_plan_id),
        (
            "declared_duration_minutes",
            context.declared_duration_minutes,
            plan.declared_duration_minutes,
        ),
    )
    for field, observed, expected in comparisons:
        if observed != expected:
            return ConstraintBlock("plan_context_mismatch", (field,))
    return None


def _require_aware_datetime(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} MUST include timezone information")


def _required_artifacts(release: RuntimeRelease) -> tuple[ArtifactRequirement, ...]:
    catalog = release.to_mapping()
    result: list[ArtifactRequirement] = []
    for section in ("services", "sidecars", "installation_agents"):
        records = catalog.get(section)
        if not isinstance(records, Mapping):
            continue
        for name, raw_record in records.items():
            if not isinstance(name, str) or not isinstance(raw_record, Mapping):
                continue
            digest = raw_record.get("image_digest")
            if isinstance(digest, str):
                result.append(ArtifactRequirement(f"{section}/{name}", digest))
    return tuple(sorted(result, key=lambda artifact: artifact.name))


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
