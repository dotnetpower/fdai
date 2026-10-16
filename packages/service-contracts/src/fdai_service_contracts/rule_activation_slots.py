"""Dormant enforcement pins and dual-revision shadow slots."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef


class RuleBindingMode(StrEnum):
    SHADOW = "shadow"
    ENFORCE = "enforce"


class RuleRevisionBindingV2(ContractBase):
    """One binding pinned to the exact revision it evaluates."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    binding_id: Annotated[str, Field(min_length=1, max_length=256)]
    revision: RuleRevisionIdentityRef
    profile_snapshot_digest: Digest
    mode: RuleBindingMode
    promotion_evidence_digest: Digest | None = None
    binding_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("binding_id", mode="before")
    @classmethod
    def _exact_id(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule revision binding id MUST be exact")
        return value

    @model_validator(mode="after")
    def _canonical_binding(self) -> Self:
        if self.mode is RuleBindingMode.ENFORCE and self.promotion_evidence_digest is None:
            raise ValueError("enforcing Rule binding requires promotion evidence")
        if self.mode is RuleBindingMode.SHADOW and self.promotion_evidence_digest is not None:
            raise ValueError("shadow Rule binding MUST NOT carry promotion evidence")
        expected = rule_revision_binding_digest(
            binding_id=self.binding_id,
            revision=self.revision,
            profile_snapshot_digest=self.profile_snapshot_digest,
            mode=self.mode,
            promotion_evidence_digest=self.promotion_evidence_digest,
        )
        if self.binding_digest != expected:
            raise ValueError("Rule revision binding digest mismatch")
        return self


class RuleDualRevisionSlotV2(ContractBase):
    """Old enforcing revision plus one prepared new shadow revision."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    rule_id: Annotated[str, Field(min_length=1, max_length=256)]
    enforcing: RuleRevisionBindingV2
    prepared_shadow: RuleRevisionBindingV2
    cohort_prepare_digest: Digest
    acknowledgement_set_digest: Digest
    created_at: datetime
    slot_digest: Digest
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule dual-revision slot time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _canonical_slot(self) -> Self:
        if (
            self.enforcing.revision.rule_id != self.rule_id
            or self.prepared_shadow.revision.rule_id != self.rule_id
            or self.enforcing.binding_id != self.prepared_shadow.binding_id
            or self.enforcing.mode is not RuleBindingMode.ENFORCE
            or self.prepared_shadow.mode is not RuleBindingMode.SHADOW
            or self.enforcing.revision == self.prepared_shadow.revision
        ):
            raise ValueError("Rule dual-revision slot binding roles are invalid")
        expected = rule_dual_revision_slot_digest(
            rule_id=self.rule_id,
            enforcing=self.enforcing,
            prepared_shadow=self.prepared_shadow,
            cohort_prepare_digest=self.cohort_prepare_digest,
            acknowledgement_set_digest=self.acknowledgement_set_digest,
            created_at=self.created_at,
        )
        if self.slot_digest != expected:
            raise ValueError("Rule dual-revision slot digest mismatch")
        return self


class RuleRevisionEvaluationEvidenceV2(ContractBase):
    """Evaluation evidence naming the exact revision and slot it ran."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    rule_id: Annotated[str, Field(min_length=1, max_length=256)]
    revision_digest: Digest
    binding_digest: Digest
    slot_digest: Digest
    mode: RuleBindingMode
    evaluation_receipt_digest: Digest
    execution_authority: Literal[False] = False


class RuleRevisionPromotionApprovalV2(ContractBase):
    """Distinct-human approval bound to one exact slot and revision evidence."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    slot_digest: Digest
    from_binding_digest: Digest
    shadow_binding_digest: Digest
    revision_evidence_digest: Digest
    approval_profile_digest: Digest
    approver_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    original_quorum: Annotated[int, Field(ge=2, le=10)]
    effective_quorum: Annotated[int, Field(ge=1, le=10)]
    approved_at: datetime
    approval_digest: Digest
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("approver_ids", mode="before")
    @classmethod
    def _exact_approvers(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or item != item.strip():
                raise ValueError("Rule revision promotion approvers MUST be exact")
            normalized.append(item)
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Rule revision promotion approvers MUST be case-insensitively unique")
        return tuple(normalized)

    @field_validator("approved_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule revision promotion approval time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _canonical_approval(self) -> Self:
        if self.approver_ids != tuple(sorted(set(self.approver_ids))):
            raise ValueError("Rule revision promotion approvers MUST be unique and sorted")
        if (
            self.effective_quorum > self.original_quorum
            or len(self.approver_ids) < self.effective_quorum
        ):
            raise ValueError("Rule revision promotion approval quorum is incomplete")
        expected = rule_revision_promotion_approval_digest(
            slot_digest=self.slot_digest,
            from_binding_digest=self.from_binding_digest,
            shadow_binding_digest=self.shadow_binding_digest,
            revision_evidence_digest=self.revision_evidence_digest,
            approval_profile_digest=self.approval_profile_digest,
            approver_ids=self.approver_ids,
            original_quorum=self.original_quorum,
            effective_quorum=self.effective_quorum,
            approved_at=self.approved_at,
        )
        if self.approval_digest != expected:
            raise ValueError("Rule revision promotion approval digest mismatch")
        return self


class RuleBindingMoveCandidateV2(ContractBase):
    """Approved but inert candidate to move one dual-revision binding."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    slot_digest: Digest
    from_binding_digest: Digest
    shadow_binding_digest: Digest
    target_enforcing: RuleRevisionBindingV2
    acknowledgement_set_digest: Digest
    applied_replica_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=1_000)]
    required_replica_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=1_000)]
    revision_evidence_digest: Digest
    promotion_approval_digest: Digest
    commanded_at: datetime
    command_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("commanded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule binding move time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _complete_applied_set(self) -> Self:
        for values in (self.applied_replica_ids, self.required_replica_ids):
            if values != tuple(sorted(set(values))):
                raise ValueError("Rule binding move replica ids MUST be unique and sorted")
        if self.applied_replica_ids != self.required_replica_ids:
            raise ValueError("Rule binding move requires every cohort replica applied")
        if (
            self.target_enforcing.mode is not RuleBindingMode.ENFORCE
            or self.target_enforcing.promotion_evidence_digest != self.promotion_approval_digest
        ):
            raise ValueError("Rule binding move target MUST be the approved enforcing binding")
        expected = rule_binding_move_candidate_digest(
            slot_digest=self.slot_digest,
            from_binding_digest=self.from_binding_digest,
            shadow_binding_digest=self.shadow_binding_digest,
            target_enforcing=self.target_enforcing,
            acknowledgement_set_digest=self.acknowledgement_set_digest,
            applied_replica_ids=self.applied_replica_ids,
            required_replica_ids=self.required_replica_ids,
            revision_evidence_digest=self.revision_evidence_digest,
            promotion_approval_digest=self.promotion_approval_digest,
            commanded_at=self.commanded_at,
        )
        if self.command_digest != expected:
            raise ValueError("Rule binding move candidate digest mismatch")
        return self


def rule_revision_binding_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_dual_revision_slot_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_binding_move_candidate_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_revision_promotion_approval_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def _json_values(values: object) -> object:
    if isinstance(values, dict):
        return {key: _json_values(value) for key, value in values.items()}
    if isinstance(values, ContractBase):
        return values.model_dump(mode="json")
    if isinstance(values, datetime):
        if values.tzinfo is None or values.utcoffset() is None:
            raise ValueError("Rule activation slot digest time MUST include a timezone")
        return values.astimezone(UTC).isoformat()
    if isinstance(values, StrEnum):
        return values.value
    if isinstance(values, tuple):
        return [_json_values(value) for value in values]
    return values


__all__ = [
    "RuleBindingMode",
    "RuleBindingMoveCandidateV2",
    "RuleDualRevisionSlotV2",
    "RuleRevisionBindingV2",
    "RuleRevisionEvaluationEvidenceV2",
    "RuleRevisionPromotionApprovalV2",
    "rule_binding_move_candidate_digest",
    "rule_dual_revision_slot_digest",
    "rule_revision_binding_digest",
    "rule_revision_promotion_approval_digest",
]
