"""Versioned models shared across the isolated Executor boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", min_length=5)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=512)]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1, max_length=512)]
_MAX_ACTION_PAYLOAD_BYTES = 262_144


class ContractBase(BaseModel):
    """Immutable, extra-forbidding base for service boundary records."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class Mode(StrEnum):
    """Autonomy mode at the time of processing.

    New capabilities always ship as :attr:`SHADOW`; promotion to
    :attr:`ENFORCE` is a separately reviewed change (see
    ``architecture.instructions.md § Safety Invariants``).
    """

    SHADOW = "shadow"
    ENFORCE = "enforce"


class ExecutionPath(StrEnum):
    """How the executor applies an action (execution-model.md 5)."""

    PR_NATIVE = "pr_native"
    DIRECT_API = "direct_api"
    PR_MANUAL = "pr_manual"
    TOOL_CALL = "tool_call"


class Operation(StrEnum):
    """Executor operation vocabulary shared by Action and its schema."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    DISABLE = "disable"
    ENABLE = "enable"
    TAG = "tag"
    DROP = "drop"
    PURGE = "purge"
    SCALE = "scale"
    RESTART = "restart"
    FAILOVER = "failover"
    ROTATE = "rotate"
    REVERT = "revert"
    ATTACH = "attach"
    DETACH = "detach"
    QUARANTINE = "quarantine"


class BlastRadiusScope(StrEnum):
    """Maximum resource scope declared by an Action."""

    RESOURCE = "resource"
    RESOURCE_GROUP = "resource_group"
    SUBSCRIPTION = "subscription"


class RollbackKind(StrEnum):
    """Recovery mechanism attached to an Action."""

    PR_REVERT = "pr_revert"
    SCRIPTED = "scripted"
    PITR = "pitr"
    SNAPSHOT_RESTORE = "snapshot_restore"
    STATE_FORWARD_ONLY = "state_forward_only"


class StopConditionKind(StrEnum):
    """Machine-evaluable stop condition vocabulary."""

    ERROR_RATE_ABOVE = "error_rate_above"
    LATENCY_P99_ABOVE_MS = "latency_p99_above_ms"
    DEPENDENT_RESOURCE_DEGRADED = "dependent_resource_degraded"
    TIME_BOX_EXCEEDED_SECONDS = "time_box_exceeded_seconds"
    PROVIDER_API_ERROR_STREAK = "provider_api_error_streak"


class OntologyDeclarationKind(StrEnum):
    """Kinds accepted by an ontology declaration reference."""

    OBJECT = "object"
    LINK = "link"
    ACTION = "action"
    INTERFACE = "interface"
    FUNCTION = "function"


class OntologyTypeRef(ContractBase):
    """Exact ontology declaration identity used to build an Action."""

    kind: OntologyDeclarationKind
    name: Annotated[str, Field(min_length=1)]
    version: SemVer
    catalog_digest: Digest


class ActionStopCondition(ContractBase):
    """One ordered machine-evaluable halt condition."""

    kind: StopConditionKind
    threshold: float | None = None
    window_seconds: Annotated[int, Field(ge=1)] | None = None
    seconds: Annotated[int, Field(ge=1)] | None = None
    count: Annotated[int, Field(ge=1)] | None = None


class RollbackRef(ContractBase):
    """Recovery contract attached to an Action."""

    kind: RollbackKind
    reference: str | None = None


class BlastRadius(ContractBase):
    """Bounded impact declaration attached to an Action."""

    scope: BlastRadiusScope
    count: int | None = Field(default=None, ge=1)
    rate_per_minute: int | None = Field(default=None, ge=1)


class WorkflowActionRef(ContractBase):
    """Workflow Process lineage, separate from ActionType arguments."""

    process_id: Annotated[str, Field(min_length=1, max_length=200)]
    step_id: Annotated[str, Field(min_length=1, max_length=200)]
    proposal_ref: Annotated[str, Field(min_length=1, max_length=512)]


class Action(ContractBase):
    """Already-gated action transported to the isolated Executor."""

    schema_version: SemVer
    action_id: UUID
    idempotency_key: IdempotencyKey
    event_id: UUID
    action_type: Annotated[str, Field(min_length=1)]
    target_resource_ref: Annotated[str, Field(min_length=1)]
    operation: Operation
    params: dict[str, Any] = Field(default_factory=dict)
    stop_condition: Annotated[str, Field(min_length=1)]
    stop_conditions: Annotated[list[ActionStopCondition], Field(min_length=1)]
    rollback_ref: RollbackRef
    blast_radius: BlastRadius
    mode: Mode
    citing_rules: Annotated[list[str], Field(min_length=1)]
    created_at: datetime
    action_type_ref: OntologyTypeRef | None = None
    executor_identity_ref: Annotated[str, Field(min_length=1)] | None = None
    workflow_action: WorkflowActionRef | None = None

    @model_validator(mode="after")
    def _stop_condition_shorthand_matches_contract(self) -> Action:
        if self.stop_conditions and self.stop_condition != self.stop_conditions[0].kind.value:
            raise ValueError("stop_condition MUST match the first structured stop condition")
        return self

    @model_validator(mode="after")
    def _action_type_reference_matches_name(self) -> Action:
        if self.action_type_ref is None:
            return self
        if self.action_type_ref.kind is not OntologyDeclarationKind.ACTION:
            raise ValueError("action_type_ref.kind MUST be action")
        if self.action_type_ref.name != self.action_type:
            raise ValueError("action_type_ref.name MUST match action_type")
        return self


class ExecutorShadowReceiptStatus(StrEnum):
    """Terminal outcomes available before Executor authority cutover."""

    SHADOWED = "shadowed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutorEffectReceiptStatus(StrEnum):
    """Terminal direct-API dispatch outcomes after authority cutover."""

    DISPATCHED = "dispatched"
    ALREADY_APPLIED = "already_applied"
    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    ABSTAINED_PRECONDITION = "abstained_precondition"
    STOPPED = "stopped"
    FAILED = "failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    POLICY_DENIED = "policy_denied"
    NETWORK_DENIED = "network_denied"
    REJECTED_MODE = "rejected_mode"
    REJECTED_INVARIANT = "rejected_invariant"
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    EXPIRED = "expired"


def executor_action_payload_digest(payload: Mapping[str, Any]) -> str:
    """Return the bounded canonical digest binding a command to its Action."""

    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("executor action payload MUST be canonical JSON") from exc
    if len(encoded) > _MAX_ACTION_PAYLOAD_BYTES:
        raise ValueError("executor action payload exceeds the transport byte limit")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ExecutorCommand(ContractBase):
    """Immutable command envelope consumed by the isolated Executor service."""

    schema_version: SemVer = "1.0.0"
    command_id: UUID
    action_schema_version: SemVer
    action_id: UUID
    event_id: UUID
    idempotency_key: IdempotencyKey
    target_resource_ref: NonEmpty
    partition_key: NonEmpty
    execution_path: ExecutionPath
    requested_mode: Mode
    attempt: Annotated[int, Field(ge=1, le=100)]
    issued_at: datetime
    deadline_at: datetime
    action_payload_digest: Digest
    action_payload: dict[str, Any]

    @classmethod
    def from_action(
        cls,
        *,
        command_id: UUID,
        action: Action,
        execution_path: ExecutionPath,
        attempt: int,
        issued_at: datetime,
        deadline_at: datetime,
    ) -> ExecutorCommand:
        """Build a command whose envelope is pinned to one validated Action."""

        payload = action.model_dump(mode="json", exclude_none=True)
        return cls(
            command_id=command_id,
            action_schema_version=action.schema_version,
            action_id=action.action_id,
            event_id=action.event_id,
            idempotency_key=action.idempotency_key,
            target_resource_ref=action.target_resource_ref,
            partition_key=action.target_resource_ref,
            execution_path=execution_path,
            requested_mode=action.mode,
            attempt=attempt,
            issued_at=issued_at,
            deadline_at=deadline_at,
            action_payload_digest=executor_action_payload_digest(payload),
            action_payload=payload,
        )

    @model_validator(mode="after")
    def _validate_transport_binding(self) -> ExecutorCommand:
        if self.issued_at.tzinfo is None or self.deadline_at.tzinfo is None:
            raise ValueError("executor command timestamps MUST be timezone-aware")
        if self.deadline_at <= self.issued_at:
            raise ValueError("executor command deadline MUST follow issue time")
        if self.partition_key != self.target_resource_ref:
            raise ValueError("executor command partition key MUST match the logical target")
        expected_payload = {
            "schema_version": self.action_schema_version,
            "action_id": str(self.action_id),
            "event_id": str(self.event_id),
            "idempotency_key": self.idempotency_key,
            "target_resource_ref": self.target_resource_ref,
            "mode": self.requested_mode.value,
        }
        for name, expected in expected_payload.items():
            if self.action_payload.get(name) != expected:
                raise ValueError(f"executor command Action {name} does not match its envelope")
        if executor_action_payload_digest(self.action_payload) != self.action_payload_digest:
            raise ValueError("executor command Action payload digest mismatch")
        return self


class ExecutorShadowReceipt(ContractBase):
    """Terminal SD-07 receipt that can never assert an applied effect."""

    schema_version: SemVer = "1.0.0"
    receipt_id: UUID
    command_id: UUID
    action_id: UUID
    idempotency_key: IdempotencyKey
    attempt: Annotated[int, Field(ge=1, le=100)]
    action_payload_digest: Digest
    requested_mode: Mode
    status: ExecutorShadowReceiptStatus
    reason: NonEmpty
    executor_instance_id: NonEmpty
    received_at: datetime
    completed_at: datetime
    effect_applied: Literal[False] = False
    audit_ref: NonEmpty | None = None

    @model_validator(mode="after")
    def _validate_shadow_receipt(self) -> ExecutorShadowReceipt:
        if self.received_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("executor receipt timestamps MUST be timezone-aware")
        if self.completed_at < self.received_at:
            raise ValueError("executor receipt completion MUST NOT precede receipt time")
        if (
            self.requested_mode is Mode.ENFORCE
            and self.status is not ExecutorShadowReceiptStatus.REJECTED
        ):
            raise ValueError("SD-07 executor receipts MUST reject enforce commands")
        return self


class ExecutorEffectReceipt(ContractBase):
    """Terminal SD-08 dispatch receipt that leaves effect verification open."""

    schema_version: SemVer = "1.1.0"
    receipt_id: UUID
    command_id: UUID
    action_id: UUID
    idempotency_key: IdempotencyKey
    attempt: Annotated[int, Field(ge=1, le=100)]
    action_payload_digest: Digest
    requested_mode: Mode
    status: ExecutorEffectReceiptStatus
    reason: NonEmpty | None = None
    executor_instance_id: NonEmpty
    received_at: datetime
    completed_at: datetime
    effect_applied: bool
    effect_verified: Literal[False] = False
    rollback_succeeded: bool | None = None
    provider_receipt_ref: NonEmpty | None = None
    audit_ref: NonEmpty

    @model_validator(mode="after")
    def _validate_effect_receipt(self) -> ExecutorEffectReceipt:
        if self.received_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("executor receipt timestamps MUST be timezone-aware")
        if self.completed_at < self.received_at:
            raise ValueError("executor receipt completion MUST NOT precede receipt time")
        effect_statuses = {
            ExecutorEffectReceiptStatus.DISPATCHED,
            ExecutorEffectReceiptStatus.ALREADY_APPLIED,
        }
        if self.effect_applied != (self.status in effect_statuses):
            raise ValueError("executor effect_applied MUST match the dispatch outcome")
        if self.effect_applied and self.requested_mode is not Mode.ENFORCE:
            raise ValueError("shadow commands cannot report an applied effect")
        return self


__all__ = [
    "Action",
    "ActionStopCondition",
    "BlastRadius",
    "BlastRadiusScope",
    "ContractBase",
    "ExecutionPath",
    "ExecutorCommand",
    "ExecutorEffectReceipt",
    "ExecutorEffectReceiptStatus",
    "ExecutorShadowReceipt",
    "ExecutorShadowReceiptStatus",
    "Mode",
    "OntologyDeclarationKind",
    "OntologyTypeRef",
    "Operation",
    "RollbackKind",
    "RollbackRef",
    "StopConditionKind",
    "WorkflowActionRef",
    "executor_action_payload_digest",
]
