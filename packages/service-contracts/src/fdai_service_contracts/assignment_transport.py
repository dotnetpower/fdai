"""Content-free Operator assignment notices, never human or execution authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

ASSIGNMENT_REQUEST_TOPIC = "operator.human-assignment.requests"
ASSIGNMENT_PROJECTION_TOPIC = "core.human-assignment.projections"
ASSIGNMENT_CONSUMER_GROUP = "core-human-assignment-v1"
ASSIGNMENT_EVENT_TYPE = "human.assignment.requested"
_DIGEST = r"^[a-f0-9]{64}$"
_REFERENCE = r"^operator-proposal:iam:[a-f0-9]{64}$"
AssignmentIntakeReason = Literal[
    "verified_operator_receipt",
    "operator_receipt_unavailable",
    "operator_receipt_mismatch",
    "operator_receipt_expired",
    "operator_receipt_unauthorized",
]


class _NoAuthorityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _explicit_values(cls, value: object, info: ValidationInfo) -> object:
        if str(info.field_name).endswith("_authority") and value is not False:
            raise ValueError("assignment transport authority MUST be explicitly false")
        if str(info.field_name).endswith("_at") and not isinstance(value, str | datetime):
            raise ValueError("assignment transport time MUST be explicit timestamp text")
        return value


def assignment_content_digest(value: Mapping[str, object]) -> str:
    """Hash canonical JSON using the existing immutable Operator proposal format."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class AssignmentRequestNotice(_NoAuthorityRecord):
    """Reference an authenticated immutable proposal without copying identity or prose.

    A consumer must independently resolve and verify the referenced Operator receipt. Neither
    this schema, its digest, nor the transport's workload identity authorizes the human request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    proposal_ref: Annotated[str, Field(pattern=_REFERENCE)]
    proposal_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    case_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    proposal_digest: Annotated[str, Field(pattern=_DIGEST)]
    operation: Literal["assignments.create", "assignments.submit", "assignments.review"]
    accepted_at: datetime
    producer_service: Literal["operator-service"] = "operator-service"
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    @model_validator(mode="after")
    def _exact_identity(self) -> AssignmentRequestNotice:
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("assignment notice accepted_at MUST be timezone-aware")
        if self.proposal_id != f"operator-{self.proposal_digest[:32]}":
            raise ValueError("assignment notice proposal identity does not match its digest")
        if self.operation == "assignments.create" and self.case_id != self.proposal_id:
            raise ValueError("assignment creation case identity MUST match its proposal")
        return self


class AssignmentIntakeProjection(_NoAuthorityRecord):
    """Inert transport disposition; it cannot claim a reviewed or active assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    proposal_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    proposal_digest: Annotated[str, Field(pattern=_DIGEST)]
    status: Literal["awaiting_agent_review", "held"]
    reason: AssignmentIntakeReason
    observed_at: datetime
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_disposition(self) -> AssignmentIntakeProjection:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("assignment intake observed_at MUST be timezone-aware")
        if (self.status == "awaiting_agent_review") != (self.reason == "verified_operator_receipt"):
            raise ValueError("assignment intake status does not match its evidence")
        if self.proposal_id != f"operator-{self.proposal_digest[:32]}":
            raise ValueError("assignment intake identity does not match its digest")
        return self


class AssignmentCaseResult(_NoAuthorityRecord):
    """Read-only case observation; active status requires both independent effect references."""

    proposal_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    request_digest: Annotated[str, Field(pattern=_DIGEST)]
    operator_case_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    case_id: Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")]
    state: Literal[
        "draft",
        "pending_review",
        "approved",
        "ownership_pr_open",
        "ownership_merged",
        "iam_applying",
        "active",
        "rejected",
        "degraded",
        "superseded",
    ]
    revision: Annotated[int, Field(strict=True, ge=1)]
    ownership_effect_ref: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    iam_effect_ref: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _verified_state(self) -> AssignmentCaseResult:
        if self.proposal_id != f"operator-{self.request_digest[:32]}":
            raise ValueError("assignment result identity does not match its digest")
        if self.state == "active" and not (self.ownership_effect_ref and self.iam_effect_ref):
            raise ValueError("active assignment result requires both effect references")
        return self


class AssignmentAgentDecision(_NoAuthorityRecord):
    """Typed, content-free command disposition carried only by fixed owner topics."""

    notice: AssignmentRequestNotice
    disposition: Literal["validated", "reviewed", "held", "materialized"]
    reason: Literal[
        "command_validated",
        "independent_review_verified",
        "case_materialized",
        "command_held",
        "review_held",
        "materialization_held",
        "agent_binding_unavailable",
    ]
    result: AssignmentCaseResult | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _consistent(self) -> AssignmentAgentDecision:
        required_reason = {
            "validated": "command_validated",
            "reviewed": "independent_review_verified",
            "materialized": "case_materialized",
        }
        if self.disposition in required_reason and self.reason != required_reason[self.disposition]:
            raise ValueError("assignment decision reason does not match disposition")
        if self.disposition == "held" and self.reason in required_reason.values():
            raise ValueError("held assignment cannot report a successful decision reason")
        if self.disposition == "reviewed" and self.notice.operation != "assignments.review":
            raise ValueError("independent review requires an assignment review command")
        if (self.disposition == "materialized") != (self.result is not None):
            raise ValueError("only a materialized assignment may carry a case result")
        if self.result is not None and (
            self.result.proposal_id != self.notice.proposal_id
            or self.result.operator_case_id != self.notice.case_id
            or self.result.request_digest != self.notice.proposal_digest
        ):
            raise ValueError("assignment materialization does not match its exact notice")
        return self


__all__ = [
    "ASSIGNMENT_CONSUMER_GROUP",
    "ASSIGNMENT_EVENT_TYPE",
    "ASSIGNMENT_PROJECTION_TOPIC",
    "ASSIGNMENT_REQUEST_TOPIC",
    "AssignmentIntakeReason",
    "AssignmentIntakeProjection",
    "AssignmentRequestNotice",
    "AssignmentAgentDecision",
    "AssignmentCaseResult",
    "assignment_content_digest",
]
