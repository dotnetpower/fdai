"""Immutable private membership execution material and current source evidence.

These values carry no enabling flag. A command still needs current independent
human decisions, unchanged source/promotion records and the shared seven-proof
bundle. Human decisions bind the original Action and material before dispatch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from fdai_service_contracts.executor_models import (
    Action,
    BlastRadiusScope,
    Operation,
    RollbackKind,
    StopConditionKind,
    executor_action_payload_digest,
)
from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan
from fdai_service_contracts.human_access_recovery import HumanAccessInverseBinding

SafeRef = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9._:-]{1,256}$")]
HexDigest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
HUMAN_ACCESS_IDENTITY = "identity/human-access"
HUMAN_ACCESS_ACTIONS = frozenset({"ops.apply-human-access", "ops.revoke-human-access"})


def canonical_human_access_json(value: object) -> str:
    """Encode source-bound JSON deterministically; unsupported values never coerce."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def human_access_record_digest(value: object) -> str:
    """Bind a retained machine record independently from its display label."""
    return hashlib.sha256(canonical_human_access_json(value).encode()).hexdigest()


def require_human_access_time(value: datetime) -> datetime:
    """Reject undefined offsets and return the same instant in UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("human access evidence timestamps MUST be timezone-aware")
    return value.astimezone(UTC)


class HumanAccessExecutionMaterial(BaseModel):
    """One private plan frozen before human review; raw subject/group never belong on the bus."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["human_access_execution_material"] = "human_access_execution_material"
    action_json: Annotated[str, Field(strict=True, min_length=1, max_length=32768)]
    subject_id: SafeRef
    group_id: SafeRef
    requested_role: Literal["Reader", "Contributor", "Approver", "Owner"]
    requester_ref: SafeRef
    case_record_digest: HexDigest
    role_groups_digest: HexDigest
    promotion_record_digest: HexDigest
    approval_ids: Annotated[tuple[SafeRef, ...], Field(min_length=1, max_length=2)]
    recorded_at: datetime
    expires_at: datetime
    inverse: HumanAccessInverseBinding | None = None

    @model_serializer(mode="wrap")
    def legacy_material_shape(self, handler: object) -> dict[str, object]:
        """Keep existing forward material bytes stable when no inverse binding is present."""
        from typing import Any, cast

        value: dict[str, object] = cast(Any, handler)(self)
        if self.inverse is None:
            value.pop("inverse", None)
        return value

    @model_validator(mode="after")
    def exact_material(self) -> HumanAccessExecutionMaterial:
        """Reject changed Action serialization, loose target identity or absent safety parameters."""
        raw = json.loads(self.action_json)
        action = Action.model_validate(raw)
        if canonical_human_access_json(action.model_dump(mode="json")) != self.action_json:
            raise ValueError("human access Action MUST use exact complete canonical JSON")
        if action.action_type not in HUMAN_ACCESS_ACTIONS:
            raise ValueError("human access material requires an existing membership ActionType")
        params = action.params
        revoke = action.action_type == "ops.revoke-human-access"
        expected = {"case_id", "expected_revision"} | (
            {"recovery_of"}
            if self.inverse is not None
            else {"replacement_revisions"}
            if revoke
            else set()
        )
        if (
            set(params) != expected
            or type(params["expected_revision"]) is not int
            or not 1 <= params["expected_revision"] <= 2147483647
        ):
            raise ValueError("human access material requires exact case arguments and revision")
        if revoke and self.inverse is None:
            replacements = params["replacement_revisions"]
            if (
                not isinstance(replacements, dict)
                or not 1 <= len(replacements) <= 30
                or any(
                    not isinstance(key, str)
                    or not key
                    or type(revision) is not int
                    or not 1 <= revision <= 2147483647
                    for key, revision in replacements.items()
                )
            ):
                raise ValueError("human access revoke requires exact replacement revisions")
        plan = self.membership_plan()
        if self.inverse is not None and (
            params["recovery_of"] != str(self.inverse.original_action_id)
            or action.action_id == self.inverse.original_action_id
            or plan.desired_membership is not self.inverse.original_before_membership
            or action.created_at <= self.inverse.original_completed_at
        ):
            raise ValueError("human access inverse MUST restore one exact original pre-state")
        target = plan.membership_lock_key.removeprefix("fdai:resource:")
        if (
            action.target_resource_ref != target
            or action.executor_identity_ref != HUMAN_ACCESS_IDENTITY
        ):
            raise ValueError(
                "human access Action MUST pin normalized membership and dedicated identity before review"
            )
        if action.operation is not (Operation.DETACH if revoke else Operation.ATTACH):
            raise ValueError("human access operation does not match the existing ActionType")
        if (
            action.blast_radius.scope is not BlastRadiusScope.RESOURCE
            or action.blast_radius.count != 1
        ):
            raise ValueError("human access blast radius MUST be exactly one membership")
        if (
            action.rollback_ref.kind is not RollbackKind.SCRIPTED
            or not action.rollback_ref.reference
        ):
            raise ValueError("human access requires a retained scripted recovery reference")
        if action.action_type_ref is None:
            raise ValueError("human access requires an exact ActionType version and catalog digest")
        conditions = {item.kind: item for item in action.stop_conditions}
        time_box = conditions.get(StopConditionKind.TIME_BOX_EXCEEDED_SECONDS)
        error_limit = conditions.get(StopConditionKind.PROVIDER_API_ERROR_STREAK)
        if (
            len(conditions) != 2
            or time_box is None
            or error_limit is None
            or time_box.seconds is None
            or not 1 <= time_box.seconds <= 120
            or error_limit.count is None
            or not 1 <= error_limit.count <= 3
        ):
            raise ValueError(
                "human access requires bounded time and provider-error stop conditions"
            )
        if (
            len(set(self.approval_ids)) != len(self.approval_ids)
            or len(self.approval_ids) != self.quorum
        ):
            raise ValueError("human access approval slots MUST match the independent human quorum")
        if any(
            value != value.casefold()
            for value in (self.subject_id, self.group_id, self.requester_ref)
        ):
            raise ValueError("human access subject, group and requester MUST already be normalized")
        start, end = (
            require_human_access_time(self.recorded_at),
            require_human_access_time(self.expires_at),
        )
        if (
            not 0 < (end - start).total_seconds() <= 300
            or require_human_access_time(action.created_at) != start
        ):
            raise ValueError(
                "human access material MUST retain its original five-minute review window"
            )
        return self

    @property
    def quorum(self) -> int:
        """Require two independent Owners for elevated access, one for ordinary access."""
        return 2 if self.requested_role in {"Approver", "Owner"} else 1

    @property
    def digest(self) -> str:
        """Address this exact inert material without mutable nested JSON."""
        return human_access_record_digest(self.model_dump(mode="json"))

    @property
    def action_digest(self) -> str:
        """Return the shared exact Action digest used by the isolated command."""
        return executor_action_payload_digest(self.action().model_dump(mode="json"))

    def action(self) -> Action:
        """Return a fresh Action value; callers cannot mutate retained JSON through it."""
        return Action.model_validate_json(self.action_json)

    def membership_plan(self) -> HumanAccessPlan:
        """Return the unchanged receipt target plus operation-independent logical lock."""
        action = self.action()
        return HumanAccessPlan(
            case_id=action.params["case_id"],
            subject_id=self.subject_id,
            group_id=self.group_id,
            operation=HumanAccessOperation.GRANT
            if action.action_type == "ops.apply-human-access"
            else HumanAccessOperation.REVOKE,
            idempotency_key=f"human-access:{action.action_id}",
        )


class HumanAccessPreparation(BaseModel):
    """Core-owned exact preparation lineage retained in the same CAS as iam_applying."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    material_digest: HexDigest
    source_case_digest: HexDigest
    source_revision: Annotated[int, Field(strict=True, ge=1)]
    prepared_revision: Annotated[int, Field(strict=True, ge=2)]

    @model_validator(mode="after")
    def exact_revision_step(self) -> HumanAccessPreparation:
        """Retain exactly r->r+1; dispatch must keep approved arguments at r."""
        if self.prepared_revision != self.source_revision + 1:
            raise ValueError("human access preparation MUST retain the exact next revision")
        return self

    @property
    def reference(self) -> str:
        """Return a deterministic content reference, not another transition authority."""
        return "human-access-prepare:" + human_access_record_digest(self.model_dump())


class HumanAccessApprovalObservation(BaseModel):
    """Read projection of one existing durable HIL slot, never another approval writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    approval_id: SafeRef
    approver_ref: SafeRef
    action_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    material_digest: HexDigest
    decision: Literal["approve", "reject"]
    decided_at: datetime
    expires_at: datetime
    source_record_digest: HexDigest


class HumanAccessCurrentEvidence(BaseModel):
    """Exact read-only current source projection; no caller-provided authority booleans."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    material_digest: HexDigest
    prepared_from_case_digest: HexDigest
    prepared_from_revision: Annotated[int, Field(strict=True, ge=1)]
    current_case_revision: Annotated[int, Field(strict=True, ge=1)]
    current_case_state: Literal["iam_applying", "degraded", "active", "iam_revoked"]
    preparation_ref: SafeRef
    role_groups_digest: HexDigest
    promotion_record_digest: HexDigest
    promotion_mode: Literal["shadow", "enforce"]
    approvals: Annotated[tuple[HumanAccessApprovalObservation, ...], Field(max_length=2)]
    current_owner_refs: Annotated[tuple[SafeRef, ...], Field(max_length=3)]
    observed_at: datetime
    expires_at: datetime

    def refusal(self, material: HumanAccessExecutionMaterial, *, now: datetime) -> str | None:
        """Only preserve eligibility from exact current evidence; never extend any deadline."""
        at = require_human_access_time(now)
        start, end = (
            require_human_access_time(self.observed_at),
            require_human_access_time(self.expires_at),
        )
        if not start <= at < end or not 0 < (end - start).total_seconds() <= 30:
            return "human_access_current_sources_expired"
        if (
            not require_human_access_time(material.recorded_at)
            <= at
            < require_human_access_time(material.expires_at)
        ):
            return "human_access_review_window_expired"
        if (
            self.material_digest != material.digest
            or self.prepared_from_case_digest != material.case_record_digest
            or self.prepared_from_revision != material.action().params["expected_revision"]
            or self.current_case_revision != self.prepared_from_revision + 1
            or self.current_case_state
            != ("degraded" if material.inverse is not None else "iam_applying")
        ):
            return "human_access_case_preparation_changed"
        if (
            self.role_groups_digest != material.role_groups_digest
            or self.promotion_record_digest != material.promotion_record_digest
            or self.promotion_mode != "enforce"
        ):
            return "human_access_source_or_promotion_changed"
        if len(self.approvals) != material.quorum or {
            item.approval_id for item in self.approvals
        } != set(material.approval_ids):
            return "human_access_current_human_quorum_missing"
        approvers = {item.approver_ref for item in self.approvals}
        owners = set(self.current_owner_refs)
        if (
            len(approvers) != material.quorum
            or len(owners) != len(self.current_owner_refs)
            or not approvers.issubset(owners)
            or material.requester_ref not in owners
            or approvers & {material.requester_ref, material.subject_id}
        ):
            return "human_access_current_human_separation_failed"
        for approval in self.approvals:
            decided = require_human_access_time(approval.decided_at)
            expires = require_human_access_time(approval.expires_at)
            if (
                approval.decision != "approve"
                or approval.material_digest != material.digest
                or approval.action_digest != material.action_digest
                or approval.approver_ref != approval.approver_ref.casefold()
                or not require_human_access_time(material.recorded_at) <= decided <= at < expires
                or expires > require_human_access_time(material.expires_at)
            ):
                return "human_access_exact_current_approval_missing"
        return None


class HumanAccessExecutionSource(Protocol):
    """Restricted material and current-source reads; no shared-state transition authority."""

    async def material_for(
        self, *, action_id: UUID, action_digest: str
    ) -> HumanAccessExecutionMaterial | None:
        """Resolve the one immutable material for the exact original Action or return absent."""
        ...

    async def current(self, material: HumanAccessExecutionMaterial) -> HumanAccessCurrentEvidence:
        """Read exact preparation, current source/promotion and original human decision records."""
        ...


__all__ = [
    "HUMAN_ACCESS_ACTIONS",
    "HUMAN_ACCESS_IDENTITY",
    "HumanAccessApprovalObservation",
    "HumanAccessCurrentEvidence",
    "HumanAccessExecutionMaterial",
    "HumanAccessExecutionSource",
    "HumanAccessPreparation",
    "canonical_human_access_json",
    "human_access_record_digest",
    "require_human_access_time",
]
