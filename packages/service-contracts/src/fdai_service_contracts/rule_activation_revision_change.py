"""Approved Rule revision changes under the authoritative v2 pointer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.rule_activation_identity import RuleActivationIdentityTransitionV2
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_slots import RuleRevisionBindingV2


class RuleRevisionChangeProposalV2(ContractBase):
    """One explicit single-Rule transition with complete source and target identity."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    source_authority_pointer_digest: Digest
    identity_transition: RuleActivationIdentityTransitionV2
    rule_id: Annotated[str, Field(min_length=1, max_length=256)]
    binding_id: Annotated[str, Field(min_length=1, max_length=256)]
    from_revision: RuleRevisionIdentityRef
    to_revision: RuleRevisionIdentityRef
    slot_digest: Digest
    binding_move_command_digest: Digest
    signed_manifest_digest: Digest
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    revision_registry_root: Digest
    cohort_prepare_digest: Digest
    reviewed_source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40,64}$")]
    proposed_by: Annotated[str, Field(min_length=1, max_length=256)]
    proposed_at: datetime
    proposal_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("rule_id", "binding_id", "release_id", "proposed_by", mode="before")
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule revision change proposal text MUST be exact")
        return value

    @field_validator("proposed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision change proposal time")

    @model_validator(mode="after")
    def _single_explicit_revision_change(self) -> Self:
        if (
            self.from_revision.rule_id != self.rule_id
            or self.to_revision.rule_id != self.rule_id
            or self.from_revision == self.to_revision
        ):
            raise ValueError("Rule revision change endpoints are invalid")
        source_members = {
            member.rule_id: member
            for member in self.identity_transition.source.profile_snapshot.members
        }
        target_members = {
            member.rule_id: member
            for member in self.identity_transition.target.profile_snapshot.members
        }
        if source_members.keys() != target_members.keys():
            raise ValueError("Rule revision change MUST preserve exact membership")
        if (
            self.identity_transition.source.profile_snapshot.profile_id
            != self.identity_transition.target.profile_snapshot.profile_id
        ):
            raise ValueError("Rule revision change MUST stay within one profile")
        changed = tuple(
            rule_id
            for rule_id in sorted(source_members)
            if source_members[rule_id] != target_members[rule_id]
        )
        if changed != (self.rule_id,):
            raise ValueError("Rule revision change MUST change exactly the named Rule")
        if (
            source_members[self.rule_id] != self.from_revision
            or target_members[self.rule_id] != self.to_revision
        ):
            raise ValueError("Rule revision change endpoints do not match the transition")
        expected = rule_revision_change_proposal_digest(
            source_authority_pointer_digest=self.source_authority_pointer_digest,
            identity_transition=self.identity_transition,
            rule_id=self.rule_id,
            binding_id=self.binding_id,
            from_revision=self.from_revision,
            to_revision=self.to_revision,
            slot_digest=self.slot_digest,
            binding_move_command_digest=self.binding_move_command_digest,
            signed_manifest_digest=self.signed_manifest_digest,
            release_id=self.release_id,
            revision_registry_root=self.revision_registry_root,
            cohort_prepare_digest=self.cohort_prepare_digest,
            reviewed_source_revision=self.reviewed_source_revision,
            proposed_by=self.proposed_by,
            proposed_at=self.proposed_at,
        )
        if self.proposal_digest != expected:
            raise ValueError("Rule revision change proposal digest mismatch")
        return self


class RuleRevisionChangeApprovalV2(ContractBase):
    """Distinct-human governance approval for one revision-change proposal."""

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
            raise ValueError("Rule revision change requester MUST be exact")
        return value

    @field_validator("approver_ids", mode="before")
    @classmethod
    def _exact_approvers(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item or item != item.strip():
                raise ValueError("Rule revision change approvers MUST be exact")
            normalized.append(item)
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Rule revision change approvers MUST be case-insensitively unique")
        return tuple(normalized)

    @field_validator("approved_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision change approval time")

    @model_validator(mode="after")
    def _canonical_approval(self) -> Self:
        if self.approver_ids != tuple(sorted(set(self.approver_ids))):
            raise ValueError("Rule revision change approvers MUST be unique and sorted")
        if self.requester_id.casefold() in {item.casefold() for item in self.approver_ids}:
            raise ValueError("Rule revision change requires a distinct human approver")
        if (
            self.effective_quorum > self.original_quorum
            or len(self.approver_ids) < self.effective_quorum
        ):
            raise ValueError("Rule revision change approval quorum is incomplete")
        expected = rule_revision_change_approval_digest(
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
            raise ValueError("Rule revision change approval digest mismatch")
        return self


class RuleRevisionChangeCommandV2(ContractBase):
    """Approved command for one exact revision and binding transition."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    proposal: RuleRevisionChangeProposalV2
    approval: RuleRevisionChangeApprovalV2
    commanded_at: datetime
    command_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator("commanded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule revision change command time")

    @model_validator(mode="after")
    def _canonical_command(self) -> Self:
        if (
            self.approval.proposal_digest != self.proposal.proposal_digest
            or self.approval.requester_id != self.proposal.proposed_by
            or self.approval.approved_at < self.proposal.proposed_at
            or self.approval.approved_at > self.commanded_at
        ):
            raise ValueError("Rule revision change approval does not match the command")
        expected = rule_revision_change_command_digest(
            proposal=self.proposal,
            approval=self.approval,
            commanded_at=self.commanded_at,
        )
        if self.command_digest != expected:
            raise ValueError("Rule revision change command digest mismatch")
        return self


class RuleBindingAuthorityPointerV2(ContractBase):
    """Authority-bearing enforcing binding selected with the generation CAS."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    revision: Annotated[int, Field(ge=1)]
    binding_id: Annotated[str, Field(min_length=1, max_length=256)]
    enforcing: RuleRevisionBindingV2
    generation_digest: Digest
    previous_binding_digest: Digest
    binding_move_command_digest: Digest
    revision_change_command_digest: Digest
    changed_at: datetime
    pointer_digest: Digest
    activation_authority: Literal[True] = True
    execution_authority: Literal[False] = False

    @field_validator("binding_id", mode="before")
    @classmethod
    def _exact_binding(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule binding authority id MUST be exact")
        return value

    @field_validator("changed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule binding authority pointer time")

    @model_validator(mode="after")
    def _canonical_pointer(self) -> Self:
        if self.enforcing.binding_id != self.binding_id:
            raise ValueError("Rule binding authority id mismatch")
        expected = rule_binding_authority_pointer_v2_digest(
            revision=self.revision,
            binding_id=self.binding_id,
            enforcing=self.enforcing,
            generation_digest=self.generation_digest,
            previous_binding_digest=self.previous_binding_digest,
            binding_move_command_digest=self.binding_move_command_digest,
            revision_change_command_digest=self.revision_change_command_digest,
            changed_at=self.changed_at,
        )
        if self.pointer_digest != expected:
            raise ValueError("Rule binding authority pointer digest mismatch")
        return self


def rule_revision_change_proposal_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_change_approval_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_change_command_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_binding_authority_pointer_v2_digest(**values: object) -> str:
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
        return _utc(values, "Rule revision change digest time").isoformat()
    if isinstance(values, tuple):
        return [_json_values(value) for value in values]
    return values


__all__ = [
    "RuleBindingAuthorityPointerV2",
    "RuleRevisionChangeApprovalV2",
    "RuleRevisionChangeCommandV2",
    "RuleRevisionChangeProposalV2",
    "rule_binding_authority_pointer_v2_digest",
    "rule_revision_change_approval_digest",
    "rule_revision_change_command_digest",
    "rule_revision_change_proposal_digest",
]
