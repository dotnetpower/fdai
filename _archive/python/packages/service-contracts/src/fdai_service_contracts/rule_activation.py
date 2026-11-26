"""Versioned, no-authority transport contracts for Rule activation generations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DIGEST_PATTERN = r"^[a-f0-9]{64}$"
_GENERATION_PATTERN = r"^rule-activation-[a-f0-9]{32}$"
_REQUEST_PATTERN = r"^rule-activation-request-[a-f0-9]{32}$"


class RuleActivationSource(StrEnum):
    """Authenticated transport that introduced an activation request."""

    INSTALLATION = "installation"
    PULL_REQUEST = "pull_request"
    DIRECT = "direct"
    OFFLINE_PACKAGE = "offline_package"


class RuleActivationStatus(StrEnum):
    """Terminal result of one exact activation command."""

    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    FAILED = "failed"


class RuleActivationDelta(BaseModel):
    """One requested membership change; it never changes enforcement authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    enabled: bool

    @field_validator("rule_id")
    @classmethod
    def _exact_rule_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("rule_id MUST NOT contain surrounding whitespace")
        return value


class RuleActivationMember(BaseModel):
    """One exact Rule artifact included in an immutable activation generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    rule_version: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    rule_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @field_validator("rule_id", "rule_version")
    @classmethod
    def _exact_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Rule activation member text MUST be exact")
        return value


class RuleActivationGeneration(BaseModel):
    """Complete immutable Rule membership selected for T0 observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    generation_id: Annotated[str, Field(pattern=_GENERATION_PATTERN)]
    generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    profile_id: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    profile_version: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    members: Annotated[tuple[RuleActivationMember, ...], Field(min_length=1, max_length=10_000)]
    created_at: datetime

    @model_validator(mode="after")
    def _canonical_identity(self) -> RuleActivationGeneration:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Rule activation generation created_at MUST be timezone-aware")
        if (
            self.profile_id != self.profile_id.strip()
            or self.profile_version != self.profile_version.strip()
        ):
            raise ValueError("Rule activation profile identity MUST be exact")
        rule_ids = tuple(member.rule_id for member in self.members)
        if rule_ids != tuple(sorted(rule_ids)) or len(set(rule_ids)) != len(rule_ids):
            raise ValueError("Rule activation members MUST be unique and sorted by rule_id")
        digest = rule_activation_generation_digest(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            catalog_digest=self.catalog_digest,
            members=self.members,
        )
        if self.generation_digest != digest:
            raise ValueError("Rule activation generation digest mismatch")
        if self.generation_id != f"rule-activation-{digest[:32]}":
            raise ValueError("Rule activation generation id mismatch")
        return self


class RuleActivationProposal(BaseModel):
    """Authenticated inert request that grants no approval or activation authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(pattern=_REQUEST_PATTERN)]
    idempotency_key: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    expected_generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)] | None
    source: RuleActivationSource
    source_ref: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    source_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    requested_by: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    requested_at: datetime
    reason: Annotated[str, Field(strict=True, min_length=20, max_length=1000)]
    changes: Annotated[tuple[RuleActivationDelta, ...], Field(min_length=1, max_length=10_000)]
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _request_invariants(self) -> RuleActivationProposal:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Rule activation requested_at MUST be timezone-aware")
        for value in (self.idempotency_key, self.source_ref, self.requested_by, self.reason):
            if value != value.strip():
                raise ValueError("Rule activation proposal text MUST be exact")
        rule_ids = tuple(change.rule_id for change in self.changes)
        if rule_ids != tuple(sorted(rule_ids)) or len(set(rule_ids)) != len(rule_ids):
            raise ValueError("Rule activation changes MUST be unique and sorted by rule_id")
        if (
            self.source
            not in {
                RuleActivationSource.INSTALLATION,
                RuleActivationSource.OFFLINE_PACKAGE,
            }
            and self.expected_generation_digest is None
        ):
            raise ValueError("Non-genesis activation requires an expected generation digest")
        digest = rule_activation_proposal_digest(
            idempotency_key=self.idempotency_key,
            expected_generation_digest=self.expected_generation_digest,
            source=self.source,
            source_ref=self.source_ref,
            source_digest=self.source_digest,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            reason=self.reason,
            changes=self.changes,
        )
        if self.request_id != f"rule-activation-request-{digest[:32]}":
            raise ValueError("Rule activation request id mismatch")
        return self

    @property
    def proposal_digest(self) -> str:
        """Return the stable digest bound by approvals and durable replay."""

        return rule_activation_proposal_digest(
            idempotency_key=self.idempotency_key,
            expected_generation_digest=self.expected_generation_digest,
            source=self.source,
            source_ref=self.source_ref,
            source_digest=self.source_digest,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            reason=self.reason,
            changes=self.changes,
        )


class RuleActivationApproval(BaseModel):
    """Current distinct-human approval bound to one exact proposal digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    approver_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    approved_at: datetime
    approval_ref: Annotated[str, Field(strict=True, min_length=1, max_length=512)]

    @model_validator(mode="after")
    def _approval_invariants(self) -> RuleActivationApproval:
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("Rule activation approved_at MUST be timezone-aware")
        if self.approval_ref != self.approval_ref.strip():
            raise ValueError("Rule activation approval_ref MUST be exact")
        if any(not value.strip() or value != value.strip() for value in self.approver_ids):
            raise ValueError("Rule activation approver identity MUST be exact")
        if len({value.casefold() for value in self.approver_ids}) != len(self.approver_ids):
            raise ValueError("Rule activation approvers MUST be distinct")
        return self


class RuleActivationCommand(BaseModel):
    """Mimir input with exact candidate generation and verified human approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    proposal: RuleActivationProposal
    approval: RuleActivationApproval
    generation: RuleActivationGeneration
    commanded_at: datetime
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _command_invariants(self) -> RuleActivationCommand:
        if self.commanded_at.tzinfo is None or self.commanded_at.utcoffset() is None:
            raise ValueError("Rule activation commanded_at MUST be timezone-aware")
        if self.approval.proposal_digest != self.proposal.proposal_digest:
            raise ValueError("Rule activation approval does not bind the proposal")
        if self.proposal.requested_by.casefold() in {
            approver.casefold() for approver in self.approval.approver_ids
        }:
            raise ValueError("Rule activation requester MUST NOT approve the same change")
        if self.approval.approved_at < self.proposal.requested_at:
            raise ValueError("Rule activation approval MUST follow the request")
        if self.commanded_at < self.approval.approved_at:
            raise ValueError("Rule activation command MUST follow approval")
        return self

    @property
    def command_digest(self) -> str:
        """Return a stable digest for idempotent command execution."""

        return _digest(
            self.model_dump(mode="json", exclude={"activation_authority", "execution_authority"})
        )


class RuleActivationResult(BaseModel):
    """Terminal application result backed by authoritative generation readback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(pattern=_REQUEST_PATTERN)]
    command_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    source: RuleActivationSource
    source_ref: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    requested_by: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    approver_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    reason: Annotated[str, Field(strict=True, min_length=20, max_length=1000)]
    changes: Annotated[tuple[RuleActivationDelta, ...], Field(min_length=1, max_length=10_000)]
    status: RuleActivationStatus
    previous_generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)] | None
    resulting_generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)] | None
    completed_at: datetime
    applied_by: Literal["Mimir"] = "Mimir"
    readback_verified: bool
    failure_reason: Annotated[str, Field(strict=True, min_length=1, max_length=256)] | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _result_invariants(self) -> RuleActivationResult:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("Rule activation completed_at MUST be timezone-aware")
        applied = self.status in {
            RuleActivationStatus.APPLIED,
            RuleActivationStatus.ALREADY_APPLIED,
        }
        if applied != self.readback_verified:
            raise ValueError("Applied Rule activation result requires verified readback")
        if applied and self.resulting_generation_digest is None:
            raise ValueError("Applied Rule activation result requires a resulting generation")
        if applied == (self.failure_reason is not None):
            raise ValueError(
                "Non-applied Rule activation result requires exactly one failure reason"
            )
        if self.requested_by in self.approver_ids:
            raise ValueError("Rule activation result cannot record self-approval")
        return self


def rule_activation_generation_digest(
    *,
    profile_id: str,
    profile_version: str,
    catalog_digest: str,
    members: tuple[RuleActivationMember, ...],
) -> str:
    """Hash the complete membership and exact Rule artifact identities."""

    return _digest(
        {
            "schema_version": "1.0.0",
            "profile_id": profile_id,
            "profile_version": profile_version,
            "catalog_digest": catalog_digest,
            "members": [member.model_dump(mode="json") for member in members],
        }
    )


def rule_activation_proposal_digest(
    *,
    idempotency_key: str,
    expected_generation_digest: str | None,
    source: RuleActivationSource,
    source_ref: str,
    source_digest: str,
    requested_by: str,
    requested_at: datetime,
    reason: str,
    changes: tuple[RuleActivationDelta, ...],
) -> str:
    """Hash every field whose meaning an approval attests."""

    return _digest(
        {
            "schema_version": "1.0.0",
            "idempotency_key": idempotency_key,
            "expected_generation_digest": expected_generation_digest,
            "source": source.value,
            "source_ref": source_ref,
            "source_digest": source_digest,
            "requested_by": requested_by,
            "requested_at": requested_at.isoformat(),
            "reason": reason,
            "changes": [change.model_dump(mode="json") for change in changes],
        }
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "RuleActivationApproval",
    "RuleActivationCommand",
    "RuleActivationDelta",
    "RuleActivationGeneration",
    "RuleActivationMember",
    "RuleActivationProposal",
    "RuleActivationResult",
    "RuleActivationSource",
    "RuleActivationStatus",
    "rule_activation_generation_digest",
    "rule_activation_proposal_digest",
]
