from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai.core.rule_activation.cohort import StateStoreRuleActivationCohort
from fdai.core.rule_activation.identity_upgrade import StateStoreRuleIdentityUpgrade
from fdai.core.rule_activation.ledger import StateStoreRuleActivationLedger
from fdai.core.rule_activation.revision_change import (
    RuleRevisionChangeConflictError,
    StateStoreRuleRevisionChanges,
)
from fdai.core.rule_activation.slots import StateStoreRuleActivationSlots
from fdai.shared.providers.rule_identity_upgrade import RuleIdentityUpgradeAuthorizer
from fdai.shared.providers.rule_revision_change import (
    RuleRevisionChangeAuthorizer,
    RuleRollbackEligibilityVerifier,
)
from fdai.shared.providers.rule_revision_promotion import RuleRevisionPromotionAuthorizer
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation_cohort import (
    RuleCohortCandidateActiveV2,
    RuleReplicaAcknowledgementV2,
    RuleReplicaAppliedV2,
    RuleReplicaDisposition,
    RuleReplicaIdentity,
    build_rule_cohort_prepare_v2,
    rule_acknowledgement_set_digest,
    rule_replica_acknowledgement_digest,
)
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
    build_rule_activation_identity_transition_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_revision_change import (
    RuleRevisionChangeApprovalV2,
    RuleRevisionChangeCommandV2,
    RuleRevisionChangeProposalV2,
    RuleRevisionTransitionKind,
    rule_revision_change_approval_digest,
    rule_revision_change_command_digest,
    rule_revision_change_proposal_digest,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleBindingMoveCandidateV2,
    RuleDualRevisionSlotV2,
    RuleRevisionBindingV2,
    rule_binding_move_candidate_digest,
    rule_dual_revision_slot_digest,
    rule_revision_binding_digest,
)
from fdai_service_contracts.rule_activation_upgrade import (
    RuleActivationAuthorityPointerV2,
    RuleActivationAuthorityTransitionKind,
    rule_activation_authority_pointer_v2_digest,
)
from fdai_service_contracts.rule_activation_versioning import (
    RuleActivationRecordKind,
    encode_rule_activation_record,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


@dataclass
class _CohortEvidence:
    cohort_value: object
    candidate_value: RuleCohortCandidateActiveV2
    acknowledgement_value: RuleReplicaAcknowledgementV2
    applied_value: RuleReplicaAppliedV2

    async def cohort(self, _prepare_digest: str) -> object:
        return self.cohort_value

    async def candidate_active(self) -> RuleCohortCandidateActiveV2:
        return self.candidate_value

    async def acknowledgement(
        self,
        _prepare_digest: str,
        _replica_id: str,
    ) -> RuleReplicaAcknowledgementV2:
        return self.acknowledgement_value

    async def applied(
        self,
        _prepare_digest: str,
        _replica_id: str,
    ) -> RuleReplicaAppliedV2:
        return self.applied_value


@dataclass
class _UpgradeAuthorizer:
    async def authorize_identity_upgrade(self, *_args: object, **_kwargs: object) -> bool:
        return True


@dataclass
class _PromotionAuthorizer:
    async def authorize(self, *_args: object, **_kwargs: object) -> bool:
        return True


@dataclass
class _RevisionAuthorizer:
    allowed: bool = True

    async def authorize_revision_change(self, *_args: object, **_kwargs: object) -> bool:
        return self.allowed


@dataclass
class _RollbackEligibility:
    expires_at: datetime | None = None

    async def rollback_eligibility_expires_at(self, _proposal: object) -> datetime | None:
        return self.expires_at


@dataclass
class _Fixture:
    store: InMemoryStateStore
    ledger: StateStoreRuleRevisionChanges
    command: RuleRevisionChangeCommandV2
    authorizer: _RevisionAuthorizer


def _binding(
    revision: RuleRevisionIdentityRef,
    *,
    profile_snapshot_digest: str,
    mode: RuleBindingMode,
    promotion_digest: str | None,
) -> RuleRevisionBindingV2:
    values = {
        "binding_id": "binding-alpha",
        "revision": revision,
        "profile_snapshot_digest": profile_snapshot_digest,
        "mode": mode,
        "promotion_evidence_digest": promotion_digest,
    }
    return RuleRevisionBindingV2(
        **values,
        binding_digest=rule_revision_binding_digest(**values),
    )


async def _fixture(
    *,
    linearization_at: datetime = NOW + timedelta(seconds=20),
    transition_kind: RuleRevisionTransitionKind = RuleRevisionTransitionKind.REVISION_CHANGE,
) -> _Fixture:
    store = InMemoryStateStore(linearization_clock=lambda: linearization_at)
    old = RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version="1.0.0",
        revision_digest=_digest("a"),
    )
    new = RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version="1.1.0",
        revision_digest=_digest("b"),
    )
    is_rollback = transition_kind is RuleRevisionTransitionKind.ROLLBACK
    source_revision = new if is_rollback else old
    target_revision = old if is_rollback else new
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.1.0" if is_rollback else "1.0.0",
        active_members=(source_revision,),
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new),
        profile_id="baseline",
        profile_version="1.2.0" if is_rollback else "1.1.0",
        active_members=(target_revision,),
    )
    transition = build_rule_activation_identity_transition_v2(source=source, target=target)
    upgrade_command_digest = _digest("c")
    current_values = {
        "revision": 1,
        "transition_kind": RuleActivationAuthorityTransitionKind.IDENTITY_UPGRADE,
        "previous_generation_digest": "d" * 64,
        "active_identity": source,
        "signed_manifest_digest": _digest("e"),
        "release_id": "release-1",
        "transition_evidence_digest": _digest("f"),
        "cohort_prepare_digest": _digest("1"),
        "acknowledgement_set_digest": _digest("2"),
        "authority_upgrade_command_digest": upgrade_command_digest,
        "transition_command_digest": upgrade_command_digest,
        "activated_at": NOW,
    }
    current = RuleActivationAuthorityPointerV2(
        **current_values,
        pointer_digest=rule_activation_authority_pointer_v2_digest(**current_values),
    )
    await store.write_state("rule-activation-v2:current", current.model_dump(mode="json"))
    await store.write_state(
        "rule-activation:current",
        encode_rule_activation_record(
            RuleActivationRecordKind.POINTER,
            {
                "revision": 2,
                "generation_id": "rule-activation-" + ("d" * 32),
                "generation_digest": "d" * 64,
                "v2_authoritative": True,
                "v2_pointer_digest": current.pointer_digest,
                "v2_upgrade_command_digest": upgrade_command_digest,
            },
        ),
    )
    replica = RuleReplicaIdentity(
        replica_id="replica-a",
        principal_id="principal-a",
        release_id="release-2",
        startup_epoch="epoch-a",
        serving_lease_id="lease-a",
        serving_lease_expires_at=NOW + timedelta(minutes=10),
    )
    cohort = build_rule_cohort_prepare_v2(
        generation=target.generation,
        serving_inventory_digest=_digest("3"),
        revision_registry_root=_digest("4"),
        catalog_manifest_digest=target.catalog_manifest.manifest_digest,
        replicas=(replica,),
        prepared_at=NOW + timedelta(seconds=10),
    )
    acknowledgement_values = {
        "prepare_digest": cohort.prepare_digest,
        "replica_id": replica.replica_id,
        "principal_id": replica.principal_id,
        "release_id": replica.release_id,
        "startup_epoch": replica.startup_epoch,
        "serving_lease_id": replica.serving_lease_id,
        "revision_registry_root": cohort.revision_registry_root,
        "catalog_manifest_digest": cohort.catalog_manifest_digest,
        "profile_snapshot_digest": cohort.generation.profile_snapshot_digest,
        "generation_digest": cohort.generation.generation_digest,
        "supported_read_schema_versions": ("1.0.0", "2.0.0"),
        "write_schema_version": "2.0.0",
        "disposition": RuleReplicaDisposition.ACKNOWLEDGED,
        "reason": "v2 write verified",
        "authentication_receipt_digest": _digest("5"),
        "observed_at": NOW + timedelta(seconds=11),
    }
    acknowledgement = RuleReplicaAcknowledgementV2(
        **acknowledgement_values,
        acknowledgement_digest=rule_replica_acknowledgement_digest(**acknowledgement_values),
    )
    acknowledgement_set_digest = rule_acknowledgement_set_digest((acknowledgement,))
    candidate_active = RuleCohortCandidateActiveV2(
        prepare_digest=cohort.prepare_digest,
        generation_digest=cohort.generation.generation_digest,
        acknowledgement_set_digest=acknowledgement_set_digest,
        activated_at=NOW + timedelta(seconds=12),
    )
    applied = RuleReplicaAppliedV2(
        prepare_digest=cohort.prepare_digest,
        acknowledgement_set_digest=acknowledgement_set_digest,
        replica_id=replica.replica_id,
        principal_id=replica.principal_id,
        release_id=replica.release_id,
        startup_epoch=replica.startup_epoch,
        serving_lease_id=replica.serving_lease_id,
        generation_digest=cohort.generation.generation_digest,
        applied_at=NOW + timedelta(seconds=13),
    )
    cohort_evidence = _CohortEvidence(cohort, candidate_active, acknowledgement, applied)
    enforcing = _binding(
        source_revision,
        profile_snapshot_digest=source.profile_snapshot.snapshot_digest,
        mode=RuleBindingMode.ENFORCE,
        promotion_digest=_digest("6"),
    )
    shadow = _binding(
        target_revision,
        profile_snapshot_digest=target.profile_snapshot.snapshot_digest,
        mode=RuleBindingMode.SHADOW,
        promotion_digest=None,
    )
    slot_values = {
        "rule_id": old.rule_id,
        "enforcing": enforcing,
        "prepared_shadow": shadow,
        "cohort_prepare_digest": cohort.prepare_digest,
        "acknowledgement_set_digest": acknowledgement_set_digest,
        "created_at": NOW + timedelta(seconds=14),
    }
    slot = RuleDualRevisionSlotV2(
        **slot_values,
        slot_digest=rule_dual_revision_slot_digest(**slot_values),
    )
    target_enforcing = _binding(
        target_revision,
        profile_snapshot_digest=target.profile_snapshot.snapshot_digest,
        mode=RuleBindingMode.ENFORCE,
        promotion_digest=_digest("7"),
    )
    move_values = {
        "slot_digest": slot.slot_digest,
        "from_binding_digest": enforcing.binding_digest,
        "shadow_binding_digest": shadow.binding_digest,
        "target_enforcing": target_enforcing,
        "acknowledgement_set_digest": acknowledgement_set_digest,
        "applied_replica_ids": (replica.replica_id,),
        "required_replica_ids": (replica.replica_id,),
        "revision_evidence_digest": _digest("8"),
        "promotion_approval_digest": _digest("7"),
        "commanded_at": NOW + timedelta(seconds=15),
    }
    move = RuleBindingMoveCandidateV2(
        **move_values,
        command_digest=rule_binding_move_candidate_digest(**move_values),
    )
    await store.write_state(
        "rule-activation-v2:slot:" + slot.slot_digest.removeprefix("sha256:"),
        slot.model_dump(mode="json"),
    )
    await store.write_state(
        "rule-activation-v2:binding-move:" + move.command_digest.removeprefix("sha256:"),
        move.model_dump(mode="json"),
    )
    await store.write_state(
        "rule-activation:manifest-nonce:" + ("9" * 64),
        {
            "manifest_digest": _digest("9"),
            "release_id": replica.release_id,
            "target_generation_id": target.generation.generation_id,
            "target_generation_digest": target.generation.generation_digest,
            "profile_id": target.profile_snapshot.profile_id,
            "profile_version": target.profile_snapshot.profile_version,
            "catalog_manifest_digest": target.catalog_manifest.manifest_digest,
            "revision_registry_root": cohort.revision_registry_root,
            "members": [target_revision.model_dump(mode="json")],
        },
    )
    proposal_values = {
        "source_authority_pointer_digest": current.pointer_digest,
        "identity_transition": transition,
        "transition_kind": transition_kind,
        "rollback_eligibility_digest": _digest("0") if is_rollback else None,
        "rollback_eligible_until": NOW + timedelta(days=7),
        "rule_id": source_revision.rule_id,
        "binding_id": enforcing.binding_id,
        "from_revision": source_revision,
        "to_revision": target_revision,
        "slot_digest": slot.slot_digest,
        "binding_move_command_digest": move.command_digest,
        "signed_manifest_digest": _digest("9"),
        "release_id": replica.release_id,
        "revision_registry_root": cohort.revision_registry_root,
        "cohort_prepare_digest": cohort.prepare_digest,
        "reviewed_source_revision": "1" * 40,
        "proposed_by": "requester-a",
        "proposed_at": NOW + timedelta(seconds=16),
    }
    proposal = RuleRevisionChangeProposalV2(
        **proposal_values,
        proposal_digest=rule_revision_change_proposal_digest(**proposal_values),
    )
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("a"),
        "approval_profile_digest": _digest("b"),
        "requester_id": proposal.proposed_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=17),
    }
    approval = RuleRevisionChangeApprovalV2(
        **approval_values,
        approval_digest=rule_revision_change_approval_digest(**approval_values),
    )
    command_values = {
        "proposal": proposal,
        "approval": approval,
        "commanded_at": NOW + timedelta(seconds=18),
    }
    command = RuleRevisionChangeCommandV2(
        **command_values,
        command_digest=rule_revision_change_command_digest(**command_values),
    )
    identity_ledger = StateStoreRuleIdentityUpgrade(
        store=store,
        legacy_ledger=StateStoreRuleActivationLedger(store=store),
        cohort_ledger=cast(StateStoreRuleActivationCohort, cohort_evidence),
        authorizer=cast(RuleIdentityUpgradeAuthorizer, _UpgradeAuthorizer()),
    )
    slots = StateStoreRuleActivationSlots(
        store=store,
        cohort_ledger=cast(StateStoreRuleActivationCohort, cohort_evidence),
        promotion_authorizer=cast(
            RuleRevisionPromotionAuthorizer,
            _PromotionAuthorizer(),
        ),
    )
    authorizer = _RevisionAuthorizer()
    ledger = StateStoreRuleRevisionChanges(
        store=store,
        identity_ledger=identity_ledger,
        cohort_ledger=cast(StateStoreRuleActivationCohort, cohort_evidence),
        slot_ledger=slots,
        authorizer=cast(RuleRevisionChangeAuthorizer, authorizer),
        rollback_eligibility=cast(
            RuleRollbackEligibilityVerifier,
            _RollbackEligibility(
                expires_at=NOW + timedelta(minutes=5) if is_rollback else None,
            ),
        ),
    )
    return _Fixture(store, ledger, command, authorizer)


async def test_revision_change_atomically_moves_generation_and_binding() -> None:
    fixture = await _fixture()

    pointer, binding = await fixture.ledger.apply(fixture.command)
    replay_pointer, replay_binding = await fixture.ledger.apply(fixture.command)

    assert replay_pointer == pointer
    assert replay_binding == binding
    assert pointer.active_identity.generation == (
        fixture.command.proposal.identity_transition.target.generation
    )
    assert binding.enforcing.revision == fixture.command.proposal.to_revision
    retained = await fixture.store.read_states(
        "rule-activation-v2:rollback-eligible:",
        limit=2,
    )
    assert len(retained) == 1
    assert await fixture.store.verify_chain()


async def test_revision_change_rejects_non_authoritative_approval() -> None:
    fixture = await _fixture()
    fixture.authorizer.allowed = False

    with pytest.raises(RuleRevisionChangeConflictError, match="not authoritative"):
        await fixture.ledger.apply(fixture.command)

    assert await fixture.store.read_state("rule-activation-v2:binding:binding-alpha") is None


async def test_revision_change_rechecks_serving_lease_at_linearization() -> None:
    fixture = await _fixture(linearization_at=NOW + timedelta(minutes=10))

    with pytest.raises(RuleRevisionChangeConflictError, match="CAS conflict"):
        await fixture.ledger.apply(fixture.command)

    current = await fixture.store.read_state("rule-activation-v2:current")
    assert current is not None
    assert current["revision"] == 1


async def test_approved_rollback_uses_the_same_cohort_and_authority_cas() -> None:
    fixture = await _fixture(transition_kind=RuleRevisionTransitionKind.ROLLBACK)

    pointer, binding = await fixture.ledger.apply(fixture.command)

    assert pointer.active_identity.profile_snapshot.members == (
        fixture.command.proposal.to_revision,
    )
    assert binding.enforcing.revision == fixture.command.proposal.to_revision
