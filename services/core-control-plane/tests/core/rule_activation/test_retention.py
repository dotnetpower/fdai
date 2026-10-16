from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai.core.rule_activation.retention import (
    RuleRevisionRetentionConflictError,
    StateStoreRuleRevisionRetention,
)
from fdai.shared.providers.rule_revision_retirement import (
    RuleRevisionRegistryReader,
    RuleRevisionRetirementAuthorizer,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
    build_rule_activation_identity_transition_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_retention import (
    RuleRevisionReferenceKind,
    RuleRevisionRetirementApprovalV2,
    RuleRevisionRetirementCommandV2,
    RuleRevisionRetirementProposalV2,
    rule_revision_retirement_approval_digest,
    rule_revision_retirement_command_digest,
    rule_revision_retirement_proposal_digest,
)
from fdai_service_contracts.rule_activation_revision_change import (
    RuleRevisionChangeProposalV2,
    RuleRevisionTransitionKind,
    RuleRollbackEligibilityV2,
    rule_revision_change_proposal_digest,
    rule_rollback_eligibility_v2_digest,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleRevisionBindingV2,
    rule_revision_binding_digest,
)
from fdai_service_contracts.rule_activation_upgrade import (
    RuleActivationAuthorityPointerV2,
    RuleActivationAuthorityTransitionKind,
    rule_activation_authority_pointer_v2_digest,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


@dataclass
class _Authorizer:
    allowed: bool = True

    async def authorize_retirement(self, *_args: object, **_kwargs: object) -> bool:
        return self.allowed


@dataclass
class _Registry:
    available: bool = True

    def has_retained_closure(self, _revision: RuleRevisionIdentityRef) -> bool:
        return self.available


def _revision(version: str, character: str) -> RuleRevisionIdentityRef:
    return RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version=version,
        revision_digest=_digest(character),
    )


def _binding(
    revision: RuleRevisionIdentityRef,
    profile_snapshot_digest: str,
) -> RuleRevisionBindingV2:
    values = {
        "binding_id": "binding-alpha",
        "revision": revision,
        "profile_snapshot_digest": profile_snapshot_digest,
        "mode": RuleBindingMode.ENFORCE,
        "promotion_evidence_digest": _digest("f"),
    }
    return RuleRevisionBindingV2(
        **values,
        binding_digest=rule_revision_binding_digest(**values),
    )


async def test_retirement_requires_authoritative_v2_state() -> None:
    ledger = StateStoreRuleRevisionRetention(
        store=InMemoryStateStore(),
        authorizer=cast(RuleRevisionRetirementAuthorizer, _Authorizer()),
        registry=cast(RuleRevisionRegistryReader, _Registry()),
    )

    with pytest.raises(RuleRevisionRetentionConflictError, match="authoritative v2"):
        await ledger.snapshot(_revision("1.0.0", "a"), captured_at=NOW)


async def test_unreferenced_revision_is_retired_with_epoch_cas() -> None:
    store = InMemoryStateStore(
        linearization_clock=lambda: NOW + timedelta(seconds=4),
    )
    authorizer = _Authorizer()
    ledger = StateStoreRuleRevisionRetention(
        store=store,
        authorizer=cast(RuleRevisionRetirementAuthorizer, authorizer),
        registry=cast(RuleRevisionRegistryReader, _Registry()),
    )
    revision = _revision("1.0.0", "a")
    active = RuleRevisionIdentityRef(
        rule_id="rule.other",
        rule_version="1.0.0",
        revision_digest=_digest("0"),
    )
    active_identity = build_rule_activation_identity_context_v2(
        catalog_revisions=(revision, active),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=(active,),
    )
    current_values = {
        "revision": 1,
        "transition_kind": RuleActivationAuthorityTransitionKind.IDENTITY_UPGRADE,
        "previous_generation_digest": "1" * 64,
        "active_identity": active_identity,
        "signed_manifest_digest": _digest("2"),
        "release_id": "release-1",
        "transition_evidence_digest": _digest("3"),
        "cohort_prepare_digest": _digest("4"),
        "acknowledgement_set_digest": _digest("5"),
        "authority_upgrade_command_digest": _digest("6"),
        "transition_command_digest": _digest("6"),
        "activated_at": NOW,
    }
    current = RuleActivationAuthorityPointerV2(
        **current_values,
        pointer_digest=rule_activation_authority_pointer_v2_digest(**current_values),
    )
    await store.write_state("rule-activation-v2:current", current.model_dump(mode="json"))
    snapshot = await ledger.snapshot(revision, captured_at=NOW)
    proposal_values = {
        "snapshot": snapshot,
        "reviewed_source_revision": "b" * 40,
        "requested_by": "requester-a",
        "requested_at": NOW + timedelta(seconds=1),
        "reason": "The revision has no remaining governed references.",
    }
    proposal = RuleRevisionRetirementProposalV2(
        **proposal_values,
        proposal_digest=rule_revision_retirement_proposal_digest(**proposal_values),
    )
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("c"),
        "approval_profile_digest": _digest("d"),
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
    command_values = {
        "proposal": proposal,
        "approval": approval,
        "commanded_at": NOW + timedelta(seconds=3),
    }
    command = RuleRevisionRetirementCommandV2(
        **command_values,
        command_digest=rule_revision_retirement_command_digest(**command_values),
    )

    receipt = await ledger.retire(command)
    replay = await ledger.retire(command)

    assert replay == receipt
    assert (
        await store.read_state(
            "rule-activation-v2:retired:" + revision.revision_digest.removeprefix("sha256:")
        )
        is not None
    )
    assert await store.verify_chain()


async def test_rollback_eligibility_blocks_retirement_and_authorizes_reverse_membership() -> None:
    store = InMemoryStateStore()
    authorizer = _Authorizer()
    ledger = StateStoreRuleRevisionRetention(
        store=store,
        authorizer=cast(RuleRevisionRetirementAuthorizer, authorizer),
        registry=cast(RuleRevisionRegistryReader, _Registry()),
    )
    old = _revision("1.0.0", "a")
    new = _revision("1.1.0", "b")
    old_identity = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=(old,),
    )
    current_identity = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.1.0",
        active_members=(new,),
    )
    rollback_identity = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.2.0",
        active_members=(old,),
    )
    eligibility_values = {
        "source_identity": old_identity,
        "source_binding": _binding(old, old_identity.profile_snapshot.snapshot_digest),
        "source_authority_pointer_digest": _digest("c"),
        "superseding_generation_digest": current_identity.generation.generation_digest,
        "release_id": "release-1",
        "signed_manifest_digest": _digest("d"),
        "revision_change_command_digest": _digest("e"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=7),
    }
    eligibility = RuleRollbackEligibilityV2(
        **eligibility_values,
        eligibility_digest=rule_rollback_eligibility_v2_digest(**eligibility_values),
    )
    current_values = {
        "revision": 2,
        "transition_kind": RuleActivationAuthorityTransitionKind.REVISION_CHANGE,
        "previous_generation_digest": old_identity.generation.generation_digest,
        "active_identity": current_identity,
        "signed_manifest_digest": _digest("d"),
        "release_id": "release-2",
        "transition_evidence_digest": _digest("8"),
        "cohort_prepare_digest": _digest("9"),
        "acknowledgement_set_digest": _digest("1"),
        "authority_upgrade_command_digest": _digest("2"),
        "transition_command_digest": eligibility.revision_change_command_digest,
        "activated_at": NOW,
    }
    current = RuleActivationAuthorityPointerV2(
        **current_values,
        pointer_digest=rule_activation_authority_pointer_v2_digest(**current_values),
    )
    await store.write_state(
        "rule-activation-v2:current",
        current.model_dump(mode="json"),
    )
    await store.write_state(
        "rule-activation-v2:rollback-eligible:"
        + eligibility.eligibility_digest.removeprefix("sha256:"),
        eligibility.model_dump(mode="json"),
    )

    snapshot = await ledger.snapshot(old, captured_at=NOW + timedelta(days=1))

    assert {item.kind for item in snapshot.references} == {
        RuleRevisionReferenceKind.ROLLBACK_ELIGIBLE
    }
    transition = build_rule_activation_identity_transition_v2(
        source=current_identity,
        target=rollback_identity,
    )
    proposal_values = {
        "source_authority_pointer_digest": current.pointer_digest,
        "identity_transition": transition,
        "transition_kind": RuleRevisionTransitionKind.ROLLBACK,
        "rollback_eligibility_digest": eligibility.eligibility_digest,
        "rollback_eligible_until": NOW + timedelta(days=14),
        "rule_id": old.rule_id,
        "binding_id": eligibility.source_binding.binding_id,
        "from_revision": new,
        "to_revision": old,
        "slot_digest": _digest("2"),
        "binding_move_command_digest": _digest("3"),
        "signed_manifest_digest": _digest("4"),
        "release_id": "release-2",
        "revision_registry_root": _digest("5"),
        "cohort_prepare_digest": _digest("6"),
        "reviewed_source_revision": "7" * 40,
        "proposed_by": "requester-a",
        "proposed_at": NOW + timedelta(days=1),
    }
    proposal = RuleRevisionChangeProposalV2(
        **proposal_values,
        proposal_digest=rule_revision_change_proposal_digest(**proposal_values),
    )

    assert await ledger.rollback_eligibility_expires_at(proposal) == eligibility.expires_at
