"""Approved Rule activation identity upgrade from version 1 to version 2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.rule_activation import RuleActivationMember
from fdai_service_contracts.rule_activation_cohort import RuleReplicaIdentity
from fdai_service_contracts.rule_activation_identity import (
    RuleActivationGenerationIdentityV2,
    RuleActivationIdentityContextV2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef

LegacyDigest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class RuleReviewedRevisionBaselineEntryV2(ContractBase):
    """Reviewed mapping from one legacy member to one full revision identity."""

    legacy_member: RuleActivationMember
    revision: RuleRevisionIdentityRef
    definition_digest: Digest
    policy_identity_digest: Digest

    @model_validator(mode="after")
    def _same_rule_identity(self) -> Self:
        if (
            self.legacy_member.rule_id != self.revision.rule_id
            or self.legacy_member.rule_version != self.revision.rule_version
        ):
            raise ValueError("Rule upgrade baseline member identity mismatch")
        expected_revision = canonical_digest(
            {
                "rule_id": self.revision.rule_id,
                "rule_version": self.revision.rule_version,
                "definition_digest": self.definition_digest,
                "policy_identity_digest": self.policy_identity_digest,
            }
        )
        if self.revision.revision_digest != expected_revision:
            raise ValueError("Rule upgrade baseline revision digest mismatch")
        return self


class RuleReviewedPolicyBaselineV2(ContractBase):
    """Human-reviewed policy identities used instead of installed bytes."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    reviewed_source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40,64}$")]
    revision_registry_root: Digest
    entries: Annotated[
        tuple[RuleReviewedRevisionBaselineEntryV2, ...],
        Field(min_length=1, max_length=10_000),
    ]
    reviewed_at: datetime
    baseline_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("release_id", mode="before")
    @classmethod
    def _exact_release(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule upgrade baseline release identity MUST be exact")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule upgrade baseline review time")

    @model_validator(mode="after")
    def _canonical_baseline(self) -> Self:
        keys = tuple(
            (entry.revision.rule_id, entry.revision.rule_version) for entry in self.entries
        )
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("Rule upgrade baseline entries MUST be unique and sorted")
        expected = rule_reviewed_policy_baseline_digest(
            release_id=self.release_id,
            reviewed_source_revision=self.reviewed_source_revision,
            revision_registry_root=self.revision_registry_root,
            entries=self.entries,
            reviewed_at=self.reviewed_at,
        )
        if self.baseline_digest != expected:
            raise ValueError("Rule upgrade baseline digest mismatch")
        return self


class RuleReplicaCompatibilityEvidenceV2(ContractBase):
    """Authenticated proof that one frozen replica can read both identity versions."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    replica: RuleReplicaIdentity
    supported_read_schema_versions: Annotated[tuple[str, ...], Field(min_length=2, max_length=8)]
    write_schema_version: Literal["1.0.0"] = "1.0.0"
    signed_manifest_digest: Digest
    verifier_principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    authentication_receipt_digest: Digest
    verified_at: datetime
    evidence_digest: Digest
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("verifier_principal_id", mode="before")
    @classmethod
    def _exact_principal(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule compatibility verifier identity MUST be exact")
        return value

    @field_validator("verified_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule compatibility verification time")

    @model_validator(mode="after")
    def _dual_read_capable(self) -> Self:
        if self.supported_read_schema_versions != tuple(
            sorted(set(self.supported_read_schema_versions))
        ):
            raise ValueError("Rule compatibility read versions MUST be unique and sorted")
        if not {"1.0.0", "2.0.0"}.issubset(self.supported_read_schema_versions):
            raise ValueError("Rule identity upgrade requires version 1 and 2 read capability")
        if self.verified_at >= self.replica.serving_lease_expires_at:
            raise ValueError("Rule compatibility evidence MUST precede serving-lease expiry")
        expected = rule_replica_compatibility_evidence_digest(
            replica=self.replica,
            supported_read_schema_versions=self.supported_read_schema_versions,
            write_schema_version=self.write_schema_version,
            signed_manifest_digest=self.signed_manifest_digest,
            verifier_principal_id=self.verifier_principal_id,
            authentication_receipt_digest=self.authentication_receipt_digest,
            verified_at=self.verified_at,
        )
        if self.evidence_digest != expected:
            raise ValueError("Rule replica compatibility evidence digest mismatch")
        return self


class RuleIdentityUpgradeProposalV2(ContractBase):
    """Inert request to replace one exact v1 identity with one exact v2 identity."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    source_generation_id: Annotated[str, Field(pattern=r"^rule-activation-[a-f0-9]{32}$")]
    source_generation_digest: LegacyDigest
    target_identity: RuleActivationIdentityContextV2
    signed_manifest_digest: Digest
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    policy_baseline_digest: Digest
    cohort_prepare_digest: Digest
    proposed_by: Annotated[str, Field(min_length=1, max_length=256)]
    proposed_at: datetime
    proposal_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("release_id", "proposed_by", mode="before")
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule identity upgrade proposal text MUST be exact")
        return value

    @field_validator("proposed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule identity upgrade proposal time")

    @model_validator(mode="after")
    def _canonical_proposal(self) -> Self:
        expected = rule_identity_upgrade_proposal_digest(
            source_generation_id=self.source_generation_id,
            source_generation_digest=self.source_generation_digest,
            target_identity=self.target_identity,
            signed_manifest_digest=self.signed_manifest_digest,
            release_id=self.release_id,
            policy_baseline_digest=self.policy_baseline_digest,
            cohort_prepare_digest=self.cohort_prepare_digest,
            proposed_by=self.proposed_by,
            proposed_at=self.proposed_at,
        )
        if self.proposal_digest != expected:
            raise ValueError("Rule identity upgrade proposal digest mismatch")
        return self


class RuleIdentityUpgradeApprovalV2(ContractBase):
    """Distinct-human approval for one exact identity-upgrade proposal."""

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
            raise ValueError("Rule identity upgrade requester MUST be exact")
        return value

    @field_validator("approver_ids", mode="before")
    @classmethod
    def _exact_approvers(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item or item != item.strip():
                raise ValueError("Rule identity upgrade approvers MUST be exact")
            normalized.append(item)
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Rule identity upgrade approvers MUST be case-insensitively unique")
        return tuple(normalized)

    @field_validator("approved_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule identity upgrade approval time")

    @model_validator(mode="after")
    def _canonical_approval(self) -> Self:
        if self.approver_ids != tuple(sorted(set(self.approver_ids))):
            raise ValueError("Rule identity upgrade approvers MUST be unique and sorted")
        if self.requester_id.casefold() in {item.casefold() for item in self.approver_ids}:
            raise ValueError("Rule identity upgrade requires a distinct human approver")
        if (
            self.effective_quorum > self.original_quorum
            or len(self.approver_ids) < self.effective_quorum
        ):
            raise ValueError("Rule identity upgrade approval quorum is incomplete")
        expected = rule_identity_upgrade_approval_digest(
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
            raise ValueError("Rule identity upgrade approval digest mismatch")
        return self


class RuleIdentityUpgradeCommandV2(ContractBase):
    """Approved command carrying every frozen replica's compatibility proof."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    proposal: RuleIdentityUpgradeProposalV2
    approval: RuleIdentityUpgradeApprovalV2
    compatibility_evidence: Annotated[
        tuple[RuleReplicaCompatibilityEvidenceV2, ...],
        Field(min_length=1, max_length=1_000),
    ]
    commanded_at: datetime
    command_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator("commanded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule identity upgrade command time")

    @model_validator(mode="after")
    def _canonical_command(self) -> Self:
        replica_ids = tuple(item.replica.replica_id for item in self.compatibility_evidence)
        if replica_ids != tuple(sorted(replica_ids)) or len(set(replica_ids)) != len(replica_ids):
            raise ValueError(
                "Rule identity upgrade compatibility evidence MUST be unique and sorted"
            )
        if (
            self.approval.proposal_digest != self.proposal.proposal_digest
            or self.approval.requester_id != self.proposal.proposed_by
            or self.approval.approved_at < self.proposal.proposed_at
            or self.approval.approved_at > self.commanded_at
        ):
            raise ValueError("Rule identity upgrade approval does not match the command")
        expected = rule_identity_upgrade_command_digest(
            proposal=self.proposal,
            approval=self.approval,
            compatibility_evidence=self.compatibility_evidence,
            commanded_at=self.commanded_at,
        )
        if self.command_digest != expected:
            raise ValueError("Rule identity upgrade command digest mismatch")
        return self


class RuleActivationAuthorityPointerV2(ContractBase):
    """The sole authority-bearing version 2 generation pointer."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    revision: Annotated[int, Field(ge=1)]
    source_generation_digest: LegacyDigest
    active_generation: RuleActivationGenerationIdentityV2
    signed_manifest_digest: Digest
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    policy_baseline_digest: Digest
    cohort_prepare_digest: Digest
    acknowledgement_set_digest: Digest
    upgrade_command_digest: Digest
    activated_at: datetime
    pointer_digest: Digest
    activation_authority: Literal[True] = True
    execution_authority: Literal[False] = False

    @field_validator("release_id", mode="before")
    @classmethod
    def _exact_release(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule activation authority release identity MUST be exact")
        return value

    @field_validator("activated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "Rule activation authority pointer time")

    @model_validator(mode="after")
    def _canonical_pointer(self) -> Self:
        expected = rule_activation_authority_pointer_v2_digest(
            revision=self.revision,
            source_generation_digest=self.source_generation_digest,
            active_generation=self.active_generation,
            signed_manifest_digest=self.signed_manifest_digest,
            release_id=self.release_id,
            policy_baseline_digest=self.policy_baseline_digest,
            cohort_prepare_digest=self.cohort_prepare_digest,
            acknowledgement_set_digest=self.acknowledgement_set_digest,
            upgrade_command_digest=self.upgrade_command_digest,
            activated_at=self.activated_at,
        )
        if self.pointer_digest != expected:
            raise ValueError("Rule activation authority pointer digest mismatch")
        return self


def rule_reviewed_policy_baseline_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_replica_compatibility_evidence_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_identity_upgrade_proposal_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_identity_upgrade_approval_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_identity_upgrade_command_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def rule_activation_authority_pointer_v2_digest(**values: object) -> str:
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
        return _utc(values, "Rule identity upgrade digest time").isoformat()
    if isinstance(values, tuple):
        return [_json_values(value) for value in values]
    return values


__all__ = [
    "RuleActivationAuthorityPointerV2",
    "RuleIdentityUpgradeApprovalV2",
    "RuleIdentityUpgradeCommandV2",
    "RuleIdentityUpgradeProposalV2",
    "RuleReplicaCompatibilityEvidenceV2",
    "RuleReviewedPolicyBaselineV2",
    "RuleReviewedRevisionBaselineEntryV2",
    "rule_activation_authority_pointer_v2_digest",
    "rule_identity_upgrade_approval_digest",
    "rule_identity_upgrade_command_digest",
    "rule_identity_upgrade_proposal_digest",
    "rule_replica_compatibility_evidence_digest",
    "rule_reviewed_policy_baseline_digest",
]
