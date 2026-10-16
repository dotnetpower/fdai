"""Rule revision retention, retirement, and rollback reference contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef


class RuleRevisionReferenceKind(StrEnum):
    ACTIVE = "active"
    DESIRED = "desired"
    PREPARED = "prepared"
    APPLIED = "applied"
    ROLLBACK_ELIGIBLE = "rollback_eligible"
    ENFORCEMENT_PIN = "enforcement_pin"
    PROMOTION_RECORD = "promotion_record"


class RuleRevisionReferenceV2(ContractBase):
    """One exact retained state object that prevents revision retirement."""

    revision: RuleRevisionIdentityRef
    kind: RuleRevisionReferenceKind
    owner_digest: Digest


class RuleRevisionRetentionSnapshotV2(ContractBase):
    """Complete bounded reference snapshot for one retirement decision."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    revision: RuleRevisionIdentityRef
    retention_epoch_revision: Annotated[int, Field(ge=1)]
    references: Annotated[tuple[RuleRevisionReferenceV2, ...], Field(max_length=50_000)]
    captured_at: datetime
    snapshot_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("captured_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision retention snapshot time")

    @model_validator(mode="after")
    def _canonical_snapshot(self) -> Self:
        keys = tuple((item.kind.value, item.owner_digest) for item in self.references)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("Rule revision references MUST be unique and sorted")
        if any(item.revision != self.revision for item in self.references):
            raise ValueError("Rule revision retention snapshot contains another revision")
        expected = rule_revision_retention_snapshot_digest(
            revision=self.revision,
            retention_epoch_revision=self.retention_epoch_revision,
            references=self.references,
            captured_at=self.captured_at,
        )
        if self.snapshot_digest != expected:
            raise ValueError("Rule revision retention snapshot digest mismatch")
        return self


class RuleRevisionRetirementProposalV2(ContractBase):
    """Inert proposal to prevent new use of one unreferenced revision."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    snapshot: RuleRevisionRetentionSnapshotV2
    reviewed_source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40,64}$")]
    requested_by: Annotated[str, Field(min_length=1, max_length=256)]
    requested_at: datetime
    reason: Annotated[str, Field(min_length=20, max_length=1_000)]
    proposal_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("requested_by", "reason", mode="before")
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule revision retirement proposal text MUST be exact")
        return value

    @field_validator("requested_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision retirement proposal time")

    @model_validator(mode="after")
    def _canonical_proposal(self) -> Self:
        if self.snapshot.references:
            raise ValueError("Referenced Rule revision cannot be proposed for retirement")
        if self.snapshot.captured_at > self.requested_at:
            raise ValueError("Rule revision retirement snapshot is newer than the request")
        expected = rule_revision_retirement_proposal_digest(
            snapshot=self.snapshot,
            reviewed_source_revision=self.reviewed_source_revision,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            reason=self.reason,
        )
        if self.proposal_digest != expected:
            raise ValueError("Rule revision retirement proposal digest mismatch")
        return self


class RuleRevisionRetirementApprovalV2(ContractBase):
    """Distinct Owner-tier approval for one exact retirement proposal."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    proposal_digest: Digest
    authority_receipt_digest: Digest
    approval_profile_digest: Digest
    requester_id: Annotated[str, Field(min_length=1, max_length=256)]
    approver_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    original_quorum: Annotated[int, Field(ge=2, le=10)]
    effective_quorum: Annotated[int, Field(ge=1, le=10)]
    approved_at: datetime
    approval_digest: Digest
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("requester_id", mode="before")
    @classmethod
    def _exact_requester(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule revision retirement requester MUST be exact")
        return value

    @field_validator("approver_ids", mode="before")
    @classmethod
    def _exact_approvers(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item or item != item.strip():
                raise ValueError("Rule revision retirement approvers MUST be exact")
            normalized.append(item)
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Rule revision retirement approvers MUST be unique")
        return tuple(normalized)

    @field_validator("approved_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision retirement approval time")

    @model_validator(mode="after")
    def _canonical_approval(self) -> Self:
        if self.approver_ids != tuple(sorted(set(self.approver_ids))):
            raise ValueError("Rule revision retirement approvers MUST be unique and sorted")
        if self.requester_id.casefold() in {item.casefold() for item in self.approver_ids}:
            raise ValueError("Rule revision retirement requires a distinct human approver")
        if (
            self.effective_quorum > self.original_quorum
            or len(self.approver_ids) < self.effective_quorum
        ):
            raise ValueError("Rule revision retirement approval quorum is incomplete")
        expected = rule_revision_retirement_approval_digest(
            proposal_digest=self.proposal_digest,
            authority_receipt_digest=self.authority_receipt_digest,
            approval_profile_digest=self.approval_profile_digest,
            requester_id=self.requester_id,
            approver_ids=self.approver_ids,
            original_quorum=self.original_quorum,
            effective_quorum=self.effective_quorum,
            approved_at=self.approved_at,
        )
        if self.approval_digest != expected:
            raise ValueError("Rule revision retirement approval digest mismatch")
        return self


class RuleRevisionRetirementCommandV2(ContractBase):
    """Approved retirement command whose current references must still be empty."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    proposal: RuleRevisionRetirementProposalV2
    approval: RuleRevisionRetirementApprovalV2
    commanded_at: datetime
    command_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator("commanded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision retirement command time")

    @model_validator(mode="after")
    def _canonical_command(self) -> Self:
        if (
            self.approval.proposal_digest != self.proposal.proposal_digest
            or self.approval.requester_id != self.proposal.requested_by
            or self.approval.approved_at < self.proposal.requested_at
            or self.approval.approved_at > self.commanded_at
            or self.commanded_at > self.approval.approved_at + timedelta(hours=24)
        ):
            raise ValueError("Rule revision retirement approval does not match the command")
        expected = rule_revision_retirement_command_digest(
            proposal=self.proposal,
            approval=self.approval,
            commanded_at=self.commanded_at,
        )
        if self.command_digest != expected:
            raise ValueError("Rule revision retirement command digest mismatch")
        return self


class RuleRevisionRetirementReceiptV2(ContractBase):
    """Durable tombstone that blocks future activation of one revision."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    revision: RuleRevisionIdentityRef
    reference_snapshot_digest: Digest
    retirement_command_digest: Digest
    retired_at: datetime
    receipt_digest: Digest
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("retired_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision retirement time")

    @model_validator(mode="after")
    def _canonical_receipt(self) -> Self:
        expected = rule_revision_retirement_receipt_digest(
            revision=self.revision,
            reference_snapshot_digest=self.reference_snapshot_digest,
            retirement_command_digest=self.retirement_command_digest,
            retired_at=self.retired_at,
        )
        if self.receipt_digest != expected:
            raise ValueError("Rule revision retirement receipt digest mismatch")
        return self


def rule_revision_retention_snapshot_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_retirement_proposal_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_retirement_approval_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_retirement_command_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_retirement_receipt_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} MUST include a timezone")
    return value.astimezone(UTC)


def _json_values(values: object) -> object:
    if isinstance(values, dict):
        return {key: _json_values(value) for key, value in values.items()}
    if isinstance(values, ContractBase):
        return values.model_dump(mode="json")
    if isinstance(values, datetime):
        return _utc(values, "Rule revision retention digest time").isoformat()
    if isinstance(values, StrEnum):
        return values.value
    if isinstance(values, tuple):
        return [_json_values(value) for value in values]
    return values


__all__ = [
    "RuleRevisionReferenceKind",
    "RuleRevisionReferenceV2",
    "RuleRevisionRetentionSnapshotV2",
    "RuleRevisionRetirementApprovalV2",
    "RuleRevisionRetirementCommandV2",
    "RuleRevisionRetirementProposalV2",
    "RuleRevisionRetirementReceiptV2",
    "rule_revision_retention_snapshot_digest",
    "rule_revision_retirement_approval_digest",
    "rule_revision_retirement_command_digest",
    "rule_revision_retirement_proposal_digest",
    "rule_revision_retirement_receipt_digest",
]
