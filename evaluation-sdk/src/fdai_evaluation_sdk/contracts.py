"""Immutable public values exchanged with an FDAI evaluation host."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai_evaluation_sdk._validation import (
    AwareDatetime,
    BoundedText,
    Identifier,
    MediaType,
    Sha256Digest,
)


class ContractModel(BaseModel):
    """Strict, immutable base for every serialized SDK contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AuthorityCeiling(StrEnum):
    """Maximum authority a session may retain after host attenuation."""

    SHADOW = "shadow"
    HIL = "hil"
    ENFORCE = "enforce"


class SideEffectClass(StrEnum):
    """Independent side-effect boundary for a semantic capability."""

    OBSERVE = "observe"
    WORKSPACE = "workspace"
    SUBSTRATE = "substrate"


class EvaluationStatus(StrEnum):
    """Terminal status returned to an external evaluation driver."""

    COMPLETED = "completed"
    HELD = "held"
    FAILED = "failed"


class WorkspaceOperation(StrEnum):
    """Reviewed operations available inside an isolated task workspace."""

    READ = "read"
    EDIT = "edit"
    BUILD = "build"
    TEST = "test"


class QualityGateStatus(StrEnum):
    """Machine-readable quality-gate result included in a decision receipt."""

    NOT_REQUIRED = "not_required"
    PASSED = "passed"
    FAILED = "failed"


class MetadataEntry(ContractModel):
    """One bounded metadata value without a mutable mapping container."""

    key: Identifier
    value: BoundedText


class Capability(ContractModel):
    """One semantic capability and its independent side-effect class."""

    capability_id: Identifier
    side_effect_class: SideEffectClass


class TargetRef(ContractModel):
    """Provider-neutral target identity."""

    kind: Identifier
    value: Identifier


class ResourceLimits(ContractModel):
    """Task-owned process and output ceilings."""

    cpu_seconds: int = Field(ge=1, le=86_400)
    memory_bytes: int = Field(ge=1_048_576, le=68_719_476_736)
    process_count: int = Field(ge=1, le=1_024)
    output_bytes: int = Field(ge=1, le=1_073_741_824)
    wall_clock_seconds: int = Field(ge=1, le=86_400)


class WorkspacePolicy(ContractModel):
    """Server-enforced limits for one isolated task root."""

    operations: tuple[WorkspaceOperation, ...] = ()
    max_files: int = Field(default=1_000, ge=1, le=100_000)
    max_total_bytes: int = Field(default=1_073_741_824, ge=1, le=68_719_476_736)

    @model_validator(mode="after")
    def _unique_operations(self) -> WorkspacePolicy:
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("workspace operations MUST be unique")
        return self


class ArtifactPolicy(ContractModel):
    """Custody limits applied to all session artifacts."""

    allowed_media_types: tuple[MediaType, ...]
    max_artifact_bytes: int = Field(ge=1, le=1_073_741_824)
    max_artifacts: int = Field(default=256, ge=1, le=4_096)
    max_ttl_seconds: int = Field(default=86_400, ge=1, le=2_592_000)
    allow_executable_outputs: bool = False

    @model_validator(mode="after")
    def _unique_media_types(self) -> ArtifactPolicy:
        if not self.allowed_media_types:
            raise ValueError("allowed_media_types MUST contain at least one media type")
        if len(set(self.allowed_media_types)) != len(self.allowed_media_types):
            raise ValueError("allowed_media_types MUST be unique")
        return self


class NetworkPolicy(ContractModel):
    """Network deny-by-default policy for isolated workspace operations."""

    deny_by_default: Literal[True] = True
    allowed_origins: tuple[Identifier, ...] = ()


class EvidenceRequirements(ContractModel):
    """Evidence and audit obligations for terminal results."""

    evidence_required: bool = True
    terminal_audit_required: bool = True


class EvaluationRequest(ContractModel):
    """Complete bounded envelope used to open one evaluation session."""

    session_id: Identifier
    requester_id: Identifier
    purpose: BoundedText
    requested_capabilities: tuple[Capability, ...]
    authority_ceiling: AuthorityCeiling
    task_count_limit: int = Field(ge=1, le=10_000)
    concurrency_limit: int = Field(ge=1, le=64)
    deadline: AwareDatetime
    workspace_policy: WorkspacePolicy
    artifact_policy: ArtifactPolicy
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    evidence_requirements: EvidenceRequirements = Field(default_factory=EvidenceRequirements)

    @model_validator(mode="after")
    def _unique_capabilities(self) -> EvaluationRequest:
        identities = tuple(item.capability_id for item in self.requested_capabilities)
        if len(set(identities)) != len(identities):
            raise ValueError("requested capabilities MUST be unique")
        return self


class ArtifactSpec(ContractModel):
    """One declared output accepted by the session artifact broker."""

    name: Identifier
    media_type: MediaType
    max_bytes: int = Field(ge=1, le=1_073_741_824)
    ttl_seconds: int = Field(default=86_400, ge=1, le=2_592_000)
    executable: bool = False


class ArtifactRef(ContractModel):
    """Content-addressed immutable artifact identity without artifact bytes."""

    artifact_id: Identifier
    session_id: Identifier
    task_id: Identifier
    name: Identifier
    media_type: MediaType
    size_bytes: int = Field(ge=0, le=1_073_741_824)
    sha256: Sha256Digest
    expires_at: AwareDatetime
    executable: bool = False


class EvaluationTask(ContractModel):
    """One benchmark-neutral unit of governed work."""

    session_id: Identifier
    task_id: Identifier
    correlation_key: Identifier | None = None
    phase: Identifier
    objective: BoundedText
    target: TargetRef
    input_artifacts: tuple[ArtifactRef, ...] = ()
    expected_outputs: tuple[ArtifactSpec, ...] = ()
    requested_capabilities: tuple[Capability, ...] = ()
    deadline: AwareDatetime
    resource_limits: ResourceLimits
    metadata: tuple[MetadataEntry, ...] = ()

    @model_validator(mode="after")
    def _validate_collections(self) -> EvaluationTask:
        _require_unique(self.input_artifacts, key=lambda item: item.artifact_id, label="inputs")
        _require_unique(self.expected_outputs, key=lambda item: item.name, label="outputs")
        _require_unique(
            self.requested_capabilities,
            key=lambda item: item.capability_id,
            label="capabilities",
        )
        _require_unique(self.metadata, key=lambda item: item.key, label="metadata keys")
        if any(item.session_id != self.session_id for item in self.input_artifacts):
            raise ValueError("input artifacts MUST belong to the task session")
        return self


class DecisionReceipt(ContractModel):
    """FDAI-controlled decision details independent from benchmark scoring."""

    selected_tier: Identifier
    control_loop_outcome: Identifier
    decision: Identifier
    autonomy_mode: AuthorityCeiling
    cited_rule_refs: tuple[Identifier, ...] = ()
    cited_evidence_refs: tuple[Identifier, ...] = ()
    action_refs: tuple[Identifier, ...] = ()
    rollback_refs: tuple[Identifier, ...] = ()
    verifier_passed: bool
    quality_gate_status: QualityGateStatus
    authority_ceiling: AuthorityCeiling


class EvaluationResult(ContractModel):
    """Correlated terminal FDAI result returned to an external driver."""

    session_id: Identifier
    task_id: Identifier
    phase: Identifier
    status: EvaluationStatus
    summary: BoundedText
    output_artifacts: tuple[ArtifactRef, ...] = ()
    evidence_refs: tuple[Identifier, ...] = ()
    terminal_audit_ref: Identifier
    decision_receipt: DecisionReceipt
    reason_code: Identifier | None = None


class ExternalValidationStage(ContractModel):
    """One external validator outcome that carries no FDAI authority."""

    stage_id: Identifier
    passed: bool
    receipt_ref: ArtifactRef


class ExternalValidationReceipt(ContractModel):
    """Untrusted benchmark evidence recorded after an FDAI session closes."""

    session_id: Identifier
    task_id: Identifier
    trusted_for_execution: Literal[False] = False
    stages: tuple[ExternalValidationStage, ...] = Field(min_length=1, max_length=32)


def _require_unique[T](
    items: tuple[T, ...],
    *,
    key: Callable[[T], Hashable],
    label: str,
) -> None:
    values = tuple(key(item) for item in items)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} MUST be unique")


__all__ = [
    "ArtifactPolicy",
    "ArtifactRef",
    "ArtifactSpec",
    "AuthorityCeiling",
    "Capability",
    "ContractModel",
    "DecisionReceipt",
    "EvaluationRequest",
    "EvaluationResult",
    "EvaluationStatus",
    "EvaluationTask",
    "EvidenceRequirements",
    "ExternalValidationReceipt",
    "ExternalValidationStage",
    "MetadataEntry",
    "NetworkPolicy",
    "QualityGateStatus",
    "ResourceLimits",
    "SideEffectClass",
    "TargetRef",
    "WorkspaceOperation",
    "WorkspacePolicy",
]
