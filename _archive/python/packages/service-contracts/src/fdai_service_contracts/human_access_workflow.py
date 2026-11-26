"""Content-free owner handoffs for exact human-access requests and independent membership reads."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.human_access_execution import (
    HexDigest,
    SafeRef,
    require_human_access_time,
)

HUMAN_ACCESS_EVENT_TYPE = "human.assignment.execution.v1"
HUMAN_ACCESS_WORK_KIND = "human_access_execution"


class HumanAccessWorkNotice(BaseModel):
    """Mechanical request identity; no bus field supplies an approval, role or membership."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: UUID
    operation: Literal["request", "decision", "reconcile", "resume", "recovery"]
    case_id: SafeRef
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    action_id: UUID | None = None
    approval_id: SafeRef | None = None
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def exact_source(self) -> HumanAccessWorkNotice:
        """Require complete phase identity and a non-sliding mechanical notice window."""
        start, end = (
            require_human_access_time(self.observed_at),
            require_human_access_time(self.expires_at),
        )
        if not 0 < (end - start).total_seconds() <= 300:
            raise ValueError("human access notice window MUST be bounded to five minutes")
        if self.operation == "request":
            if self.action_id is not None or self.approval_id is not None:
                raise ValueError("human access request cannot supply existing execution authority")
        elif self.action_id is None or (self.operation == "decision") != (
            self.approval_id is not None
        ):
            raise ValueError("human access phase requires its exact material and decision identity")
        return self


class HumanAccessHandoff(BaseModel):
    """Typed reference-only agent result; Saga provenance is checked separately on each topic."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    notice: HumanAccessWorkNotice
    stage: Literal[
        "proposed",
        "awaiting_human",
        "decision_checked",
        "human_reviewed",
        "prepared",
        "dispatch_ready",
        "dispatch_pending",
        "dispatch_observed",
        "effect_observed",
        "effect_checked",
        "effect_recorded",
        "effect_mismatch",
        "recovery_held",
        "recovery_observed",
        "recovery_judged",
        "recovery_proposed",
        "recovery_verified",
        "recovery_recorded",
        "held",
    ]
    action_id: UUID | None = None
    material_digest: HexDigest | None = None
    evidence_ref: SafeRef | None = None
    reason: SafeRef | None = None
    execution_authority: Literal[False] = False

    @field_validator("execution_authority", mode="before")
    @classmethod
    def no_coerced_authority(cls, value: object) -> object:
        """Even a negative authority flag must be an exact boolean, never numeric coercion."""
        if value is not False:
            raise ValueError("human access handoff grants no execution authority")
        return value

    @model_validator(mode="after")
    def references_only(self) -> HumanAccessHandoff:
        """A successful stage always names retained material; a hold remains explicit."""
        if self.stage == "held":
            if self.reason is None:
                raise ValueError("human access hold requires an explicit bounded reason")
        elif self.action_id is None or self.material_digest is None:
            raise ValueError("human access stage requires exact retained material identity")
        return self


class HumanAccessMembershipObservation(BaseModel):
    """Heimdall's independent current read, not an Executor acknowledgement or permission."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["human_access_membership_observation"] = "human_access_membership_observation"
    material_digest: HexDigest
    action_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    target_digest: HexDigest
    dispatch_receipt_digest: HexDigest
    state: Literal["membership_present", "membership_absent"]
    observer_identity_ref: SafeRef
    source_ref: SafeRef
    observed_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def current_window(self) -> HumanAccessMembershipObservation:
        """Bound source freshness and require a separately identified read principal."""
        start, end = (
            require_human_access_time(self.observed_at),
            require_human_access_time(self.valid_until),
        )
        if not 0 < (end - start).total_seconds() <= 60:
            raise ValueError("human access independent observation MUST expire within one minute")
        return self


__all__ = [
    "HUMAN_ACCESS_EVENT_TYPE",
    "HUMAN_ACCESS_WORK_KIND",
    "HumanAccessWorkNotice",
    "HumanAccessHandoff",
    "HumanAccessMembershipObservation",
]
