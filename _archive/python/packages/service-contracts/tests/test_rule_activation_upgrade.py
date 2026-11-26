from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.rule_activation import RuleActivationMember
from fdai_service_contracts.rule_activation_cohort import RuleReplicaIdentity
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_upgrade import (
    RuleActivationAuthorityPointerV2,
    RuleActivationAuthorityTransitionKind,
    RuleIdentityUpgradeApprovalV2,
    RuleIdentityUpgradeCommandV2,
    RuleIdentityUpgradeProposalV2,
    RuleReplicaCompatibilityEvidenceV2,
    RuleReviewedPolicyBaselineV2,
    RuleReviewedRevisionBaselineEntryV2,
    rule_activation_authority_pointer_v2_digest,
    rule_identity_upgrade_approval_digest,
    rule_identity_upgrade_command_digest,
    rule_identity_upgrade_proposal_digest,
    rule_replica_compatibility_evidence_digest,
    rule_reviewed_policy_baseline_digest,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _fixture() -> tuple[
    RuleReviewedPolicyBaselineV2,
    RuleIdentityUpgradeProposalV2,
    RuleReplicaCompatibilityEvidenceV2,
]:
    legacy = RuleActivationMember(
        rule_id="rule.alpha",
        rule_version="1.0.0",
        rule_digest="a" * 64,
    )
    definition_digest = _digest("c")
    policy_identity_digest = _digest("d")
    revision = RuleRevisionIdentityRef(
        rule_id=legacy.rule_id,
        rule_version=legacy.rule_version,
        revision_digest=canonical_digest(
            {
                "rule_id": legacy.rule_id,
                "rule_version": legacy.rule_version,
                "definition_digest": definition_digest,
                "policy_identity_digest": policy_identity_digest,
            }
        ),
    )
    context = build_rule_activation_identity_context_v2(
        catalog_revisions=(revision,),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=(revision,),
    )
    entry = RuleReviewedRevisionBaselineEntryV2(
        legacy_member=legacy,
        revision=revision,
        definition_digest=definition_digest,
        policy_identity_digest=policy_identity_digest,
    )
    baseline_values = {
        "release_id": "release-1",
        "reviewed_source_revision": "e" * 40,
        "revision_registry_root": _digest("f"),
        "entries": (entry,),
        "reviewed_at": NOW,
    }
    baseline = RuleReviewedPolicyBaselineV2(
        **baseline_values,
        baseline_digest=rule_reviewed_policy_baseline_digest(**baseline_values),
    )
    proposal_values = {
        "source_generation_id": "rule-activation-" + ("1" * 32),
        "source_generation_digest": "2" * 64,
        "target_identity": context,
        "signed_manifest_digest": _digest("3"),
        "release_id": baseline.release_id,
        "policy_baseline_digest": baseline.baseline_digest,
        "cohort_prepare_digest": _digest("4"),
        "proposed_by": "requester-a",
        "proposed_at": NOW + timedelta(seconds=1),
    }
    proposal = RuleIdentityUpgradeProposalV2(
        **proposal_values,
        proposal_digest=rule_identity_upgrade_proposal_digest(**proposal_values),
    )
    replica = RuleReplicaIdentity(
        replica_id="replica-a",
        principal_id="principal-a",
        release_id=baseline.release_id,
        startup_epoch="epoch-a",
        serving_lease_id="lease-a",
        serving_lease_expires_at=NOW + timedelta(minutes=10),
    )
    compatibility_values = {
        "replica": replica,
        "supported_read_schema_versions": ("1.0.0", "2.0.0"),
        "write_schema_version": "1.0.0",
        "signed_manifest_digest": proposal.signed_manifest_digest,
        "verifier_principal_id": "verifier-a",
        "authentication_receipt_digest": _digest("5"),
        "verified_at": NOW + timedelta(seconds=2),
    }
    compatibility = RuleReplicaCompatibilityEvidenceV2(
        **compatibility_values,
        evidence_digest=rule_replica_compatibility_evidence_digest(**compatibility_values),
    )
    return baseline, proposal, compatibility


def _approval(proposal: RuleIdentityUpgradeProposalV2) -> RuleIdentityUpgradeApprovalV2:
    values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("6"),
        "approval_profile_digest": _digest("7"),
        "requester_id": proposal.proposed_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=3),
    }
    return RuleIdentityUpgradeApprovalV2(
        **values,
        approval_digest=rule_identity_upgrade_approval_digest(**values),
    )


def test_upgrade_contract_binds_review_compatibility_and_authority_pointer() -> None:
    baseline, proposal, compatibility = _fixture()
    approval = _approval(proposal)
    command_values = {
        "proposal": proposal,
        "approval": approval,
        "compatibility_evidence": (compatibility,),
        "commanded_at": NOW + timedelta(seconds=4),
    }
    command = RuleIdentityUpgradeCommandV2(
        **command_values,
        command_digest=rule_identity_upgrade_command_digest(**command_values),
    )
    pointer_values = {
        "revision": 1,
        "transition_kind": RuleActivationAuthorityTransitionKind.IDENTITY_UPGRADE,
        "previous_generation_digest": proposal.source_generation_digest,
        "active_identity": proposal.target_identity,
        "signed_manifest_digest": proposal.signed_manifest_digest,
        "release_id": baseline.release_id,
        "transition_evidence_digest": baseline.baseline_digest,
        "cohort_prepare_digest": proposal.cohort_prepare_digest,
        "acknowledgement_set_digest": _digest("8"),
        "authority_upgrade_command_digest": command.command_digest,
        "transition_command_digest": command.command_digest,
        "activated_at": command.commanded_at,
    }
    pointer = RuleActivationAuthorityPointerV2(
        **pointer_values,
        pointer_digest=rule_activation_authority_pointer_v2_digest(**pointer_values),
    )

    assert pointer.activation_authority is True
    assert pointer.active_identity.generation == proposal.target_identity.generation


def test_upgrade_approval_rejects_requester_self_approval() -> None:
    _, proposal, _ = _fixture()
    values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("6"),
        "approval_profile_digest": _digest("7"),
        "requester_id": proposal.proposed_by,
        "approver_ids": (proposal.proposed_by,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": NOW + timedelta(seconds=3),
    }

    with pytest.raises(ValueError, match="distinct human"):
        RuleIdentityUpgradeApprovalV2(
            **values,
            approval_digest=rule_identity_upgrade_approval_digest(**values),
        )


def test_upgrade_compatibility_requires_both_read_versions() -> None:
    _, proposal, compatibility = _fixture()
    values = {
        **compatibility.model_dump(),
        "supported_read_schema_versions": ("1.0.0", "3.0.0"),
    }
    values["evidence_digest"] = rule_replica_compatibility_evidence_digest(
        **{key: value for key, value in values.items() if key != "evidence_digest"}
    )

    with pytest.raises(ValueError, match="version 1 and 2"):
        RuleReplicaCompatibilityEvidenceV2.model_validate(values)


def test_reviewed_baseline_rejects_legacy_to_revision_identity_drift() -> None:
    baseline, _, _ = _fixture()
    entry = baseline.entries[0]

    with pytest.raises(ValueError, match="member identity mismatch"):
        RuleReviewedRevisionBaselineEntryV2(
            legacy_member=entry.legacy_member,
            revision=entry.revision.model_copy(update={"rule_id": "rule.other"}),
            definition_digest=entry.definition_digest,
            policy_identity_digest=entry.policy_identity_digest,
        )
