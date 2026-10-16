from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.rbac.roles import Role
from fdai.delivery.persistence.state_store_rule_activation_authority import (
    StateStoreRuleActivationAuthority,
)
from fdai.delivery.promotion_attestation import (
    GovernancePromotionAttestation,
    promotion_attestation_digest,
)
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.rule_activation import RuleActivationMember
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
    build_rule_activation_identity_transition_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_retention import (
    RuleRevisionRetentionSnapshotV2,
    RuleRevisionRetirementApprovalV2,
    RuleRevisionRetirementProposalV2,
    rule_revision_retention_snapshot_digest,
    rule_revision_retirement_approval_digest,
    rule_revision_retirement_proposal_digest,
)
from fdai_service_contracts.rule_activation_revision_change import (
    RuleRevisionChangeApprovalV2,
    RuleRevisionChangeProposalV2,
    RuleRevisionTransitionKind,
    rule_revision_change_approval_digest,
    rule_revision_change_proposal_digest,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleDualRevisionSlotV2,
    RuleRevisionBindingV2,
    RuleRevisionPromotionApprovalV2,
    rule_dual_revision_slot_digest,
    rule_revision_binding_digest,
    rule_revision_promotion_approval_digest,
)
from fdai_service_contracts.rule_activation_upgrade import (
    RuleIdentityUpgradeApprovalV2,
    RuleIdentityUpgradeProposalV2,
    RuleReviewedPolicyBaselineV2,
    RuleReviewedRevisionBaselineEntryV2,
    rule_identity_upgrade_approval_digest,
    rule_identity_upgrade_proposal_digest,
    rule_reviewed_policy_baseline_digest,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)
HEAD = "a" * 40


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _profile(revision_id: str = "approval-profile-r1") -> ApprovalProfileRevision:
    values = {
        "revision_id": revision_id,
        "approval_profile": ApprovalProfileKind.MULTI_OPERATOR.value,
        "executor_principal": "executor-a",
        "effective_from": NOW.isoformat(),
        "operator_principal": None,
    }
    return ApprovalProfileRevision(
        revision_id=values["revision_id"],
        approval_profile=ApprovalProfileKind.MULTI_OPERATOR,
        executor_principal=values["executor_principal"],
        policy_digest=approval_profile_policy_digest(values),
        effective_from=NOW,
    )


def _attestation(
    *,
    action_type_id: str,
    evidence_digest: str,
    idempotency_key: str,
    scenario_set_version: str,
    request_fingerprint: str,
    author: str = "requester-a",
    change_class: GovernanceChangeClass = GovernanceChangeClass.ENFORCE_PROMOTION,
) -> GovernancePromotionAttestation:
    roles = frozenset({Role.APPROVER, Role.OWNER})
    approvals = (
        GovernanceApproval(
            approver=GovernancePrincipal(oid="approver-a", roles=roles),
            reviewed_revision=HEAD,
            approved_at=NOW + timedelta(seconds=1),
            phishing_resistant=True,
        ),
        GovernanceApproval(
            approver=GovernancePrincipal(oid="approver-b", roles=roles),
            reviewed_revision=HEAD,
            approved_at=NOW + timedelta(seconds=2),
            phishing_resistant=True,
        ),
    )
    return GovernancePromotionAttestation(
        review=GovernanceReviewRequest(
            change_class=change_class,
            author=GovernancePrincipal(oid=author, roles=roles),
            head_revision=HEAD,
            head_committed_at=NOW,
            approvals=approvals,
            approval_profile=_profile(),
        ),
        action_type_id=action_type_id,
        fdai_revision=HEAD,
        scenario_set_version=scenario_set_version,
        evidence_digest=evidence_digest,
        idempotency_key=idempotency_key,
        nonce="nonce-a",
        request_fingerprint=request_fingerprint,
    )


async def _retain_attestation(
    store: InMemoryStateStore,
    attestation: GovernancePromotionAttestation,
) -> str:
    digest = promotion_attestation_digest(attestation)
    await store.write_state(
        "governance-promotion-attestation:" + digest,
        {
            "state": "reserved",
            "approval_receipt_digest": digest,
            "attestation": attestation.as_json(),
        },
    )
    return "sha256:" + digest


def _slot() -> RuleDualRevisionSlotV2:
    old = RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version="1.0.0",
        revision_digest=_digest("b"),
    )
    new = RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version="1.1.0",
        revision_digest=_digest("c"),
    )
    enforcing_values = {
        "binding_id": "binding-alpha",
        "revision": old,
        "profile_snapshot_digest": _digest("d"),
        "mode": RuleBindingMode.ENFORCE,
        "promotion_evidence_digest": _digest("e"),
    }
    enforcing = RuleRevisionBindingV2(
        **enforcing_values,
        binding_digest=rule_revision_binding_digest(**enforcing_values),
    )
    shadow_values = {
        "binding_id": "binding-alpha",
        "revision": new,
        "profile_snapshot_digest": _digest("f"),
        "mode": RuleBindingMode.SHADOW,
        "promotion_evidence_digest": None,
    }
    shadow = RuleRevisionBindingV2(
        **shadow_values,
        binding_digest=rule_revision_binding_digest(**shadow_values),
    )
    values = {
        "rule_id": new.rule_id,
        "enforcing": enforcing,
        "prepared_shadow": shadow,
        "cohort_prepare_digest": _digest("1"),
        "acknowledgement_set_digest": _digest("2"),
        "created_at": NOW,
    }
    return RuleDualRevisionSlotV2(
        **values,
        slot_digest=rule_dual_revision_slot_digest(**values),
    )


async def test_revision_promotion_requires_exact_durable_governance_attestation() -> None:
    store = InMemoryStateStore()
    slot = _slot()
    attestation = _attestation(
        action_type_id="rule-revision-promote",
        evidence_digest=_digest("3"),
        idempotency_key=slot.slot_digest,
        scenario_set_version=slot.prepared_shadow.revision.rule_version,
        request_fingerprint=slot.prepared_shadow.revision.revision_digest,
    )
    receipt_digest = await _retain_attestation(store, attestation)
    values = {
        "slot_digest": slot.slot_digest,
        "from_binding_digest": slot.enforcing.binding_digest,
        "shadow_binding_digest": slot.prepared_shadow.binding_digest,
        "revision_evidence_digest": attestation.evidence_digest,
        "authority_receipt_digest": receipt_digest,
        "approval_profile_digest": _profile().policy_digest,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=2),
    }
    approval = RuleRevisionPromotionApprovalV2(
        **values,
        approval_digest=rule_revision_promotion_approval_digest(**values),
    )
    authority = StateStoreRuleActivationAuthority(
        store,
        active_approval_profile=_profile(),
    )

    assert await authority.authorize(
        approval,
        slot=slot,
        target_revision=slot.prepared_shadow.revision,
    )
    assert not await authority.authorize(
        approval.model_copy(update={"revision_evidence_digest": _digest("4")}),
        slot=slot,
        target_revision=slot.prepared_shadow.revision,
    )
    stale_authority = StateStoreRuleActivationAuthority(
        store,
        active_approval_profile=_profile("approval-profile-r2"),
    )
    assert not await stale_authority.authorize(
        approval,
        slot=slot,
        target_revision=slot.prepared_shadow.revision,
    )


async def test_identity_upgrade_requires_reviewed_source_and_exact_proposer() -> None:
    store = InMemoryStateStore()
    legacy = RuleActivationMember(
        rule_id="rule.alpha",
        rule_version="1.0.0",
        rule_digest="1" * 64,
    )
    definition_digest = _digest("6")
    policy_identity_digest = _digest("7")
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
        "reviewed_source_revision": HEAD,
        "revision_registry_root": _digest("8"),
        "entries": (entry,),
        "reviewed_at": NOW,
    }
    baseline = RuleReviewedPolicyBaselineV2(
        **baseline_values,
        baseline_digest=rule_reviewed_policy_baseline_digest(**baseline_values),
    )
    proposal_values = {
        "source_generation_id": "rule-activation-" + ("2" * 32),
        "source_generation_digest": "3" * 64,
        "target_identity": context,
        "signed_manifest_digest": _digest("9"),
        "release_id": baseline.release_id,
        "policy_baseline_digest": baseline.baseline_digest,
        "cohort_prepare_digest": _digest("a"),
        "proposed_by": "requester-a",
        "proposed_at": NOW,
    }
    proposal = RuleIdentityUpgradeProposalV2(
        **proposal_values,
        proposal_digest=rule_identity_upgrade_proposal_digest(**proposal_values),
    )
    attestation = _attestation(
        action_type_id="rule-identity-upgrade",
        evidence_digest=proposal.proposal_digest,
        idempotency_key=proposal.proposal_digest,
        scenario_set_version=context.profile_snapshot.profile_version,
        request_fingerprint=context.generation.generation_digest,
    )
    receipt_digest = await _retain_attestation(store, attestation)
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": receipt_digest,
        "approval_profile_digest": _profile().policy_digest,
        "requester_id": proposal.proposed_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=2),
    }
    approval = RuleIdentityUpgradeApprovalV2(
        **approval_values,
        approval_digest=rule_identity_upgrade_approval_digest(**approval_values),
    )
    authority = StateStoreRuleActivationAuthority(
        store,
        active_approval_profile=_profile(),
    )

    assert await authority.authorize_identity_upgrade(
        approval,
        proposal=proposal,
        baseline=baseline,
    )
    assert not await authority.authorize_identity_upgrade(
        approval,
        proposal=proposal.model_copy(update={"proposed_by": "requester-other"}),
        baseline=baseline,
    )


async def test_revision_change_authority_binds_complete_target_transition() -> None:
    store = InMemoryStateStore()
    old = RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version="1.0.0",
        revision_digest=_digest("1"),
    )
    new = RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version="1.1.0",
        revision_digest=_digest("2"),
    )
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=(old,),
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.1.0",
        active_members=(new,),
    )
    transition = build_rule_activation_identity_transition_v2(source=source, target=target)
    proposal_values = {
        "source_authority_pointer_digest": _digest("3"),
        "identity_transition": transition,
        "transition_kind": RuleRevisionTransitionKind.REVISION_CHANGE,
        "rollback_eligibility_digest": None,
        "rollback_eligible_until": NOW + timedelta(days=7),
        "rule_id": old.rule_id,
        "binding_id": "binding-alpha",
        "from_revision": old,
        "to_revision": new,
        "slot_digest": _digest("4"),
        "binding_move_command_digest": _digest("5"),
        "signed_manifest_digest": _digest("6"),
        "release_id": "release-2",
        "revision_registry_root": _digest("7"),
        "cohort_prepare_digest": _digest("8"),
        "reviewed_source_revision": HEAD,
        "proposed_by": "requester-a",
        "proposed_at": NOW,
    }
    proposal = RuleRevisionChangeProposalV2(
        **proposal_values,
        proposal_digest=rule_revision_change_proposal_digest(**proposal_values),
    )
    attestation = _attestation(
        action_type_id="rule-revision-change",
        evidence_digest=proposal.proposal_digest,
        idempotency_key=proposal.proposal_digest,
        scenario_set_version=target.profile_snapshot.profile_version,
        request_fingerprint=target.generation.generation_digest,
    )
    receipt_digest = await _retain_attestation(store, attestation)
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": receipt_digest,
        "approval_profile_digest": _profile().policy_digest,
        "requester_id": proposal.proposed_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=2),
    }
    approval = RuleRevisionChangeApprovalV2(
        **approval_values,
        approval_digest=rule_revision_change_approval_digest(**approval_values),
    )
    authority = StateStoreRuleActivationAuthority(
        store,
        active_approval_profile=_profile(),
    )

    assert await authority.authorize_revision_change(
        approval,
        proposal=proposal,
    )
    assert not await authority.authorize_revision_change(
        approval,
        proposal=proposal.model_copy(update={"reviewed_source_revision": "b" * 40}),
    )


async def test_retirement_authority_requires_owner_review_of_zero_reference_snapshot() -> None:
    store = InMemoryStateStore()
    revision = RuleRevisionIdentityRef(
        rule_id="rule.retired",
        rule_version="1.0.0",
        revision_digest=_digest("9"),
    )
    snapshot_values = {
        "revision": revision,
        "retention_epoch_revision": 4,
        "references": (),
        "captured_at": NOW,
    }
    snapshot = RuleRevisionRetentionSnapshotV2(
        **snapshot_values,
        snapshot_digest=rule_revision_retention_snapshot_digest(**snapshot_values),
    )
    proposal_values = {
        "snapshot": snapshot,
        "reviewed_source_revision": HEAD,
        "requested_by": "requester-a",
        "requested_at": NOW,
        "reason": "The revision has no remaining governed references.",
    }
    proposal = RuleRevisionRetirementProposalV2(
        **proposal_values,
        proposal_digest=rule_revision_retirement_proposal_digest(**proposal_values),
    )
    attestation = _attestation(
        action_type_id="rule-revision-retire",
        evidence_digest=proposal.proposal_digest,
        idempotency_key=proposal.proposal_digest,
        scenario_set_version=revision.rule_version,
        request_fingerprint=revision.revision_digest,
        change_class=GovernanceChangeClass.RULE_RETIREMENT,
    )
    receipt_digest = await _retain_attestation(store, attestation)
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": receipt_digest,
        "approval_profile_digest": _profile().policy_digest,
        "requester_id": proposal.requested_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=2),
    }
    approval = RuleRevisionRetirementApprovalV2(
        **approval_values,
        approval_digest=rule_revision_retirement_approval_digest(**approval_values),
    )
    authority = StateStoreRuleActivationAuthority(
        store,
        active_approval_profile=_profile(),
    )

    assert await authority.authorize_retirement(
        approval,
        proposal=proposal,
    )
