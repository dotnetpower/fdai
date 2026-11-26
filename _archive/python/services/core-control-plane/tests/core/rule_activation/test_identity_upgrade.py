from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai.core.rule_activation.cohort import StateStoreRuleActivationCohort
from fdai.core.rule_activation.identity_upgrade import (
    RuleIdentityUpgradeConflictError,
    StateStoreRuleIdentityUpgrade,
)
from fdai.core.rule_activation.ledger import StateStoreRuleActivationLedger
from fdai.shared.providers.rule_identity_upgrade import RuleIdentityUpgradeAuthorizer
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.rule_activation import (
    RuleActivationApproval,
    RuleActivationCommand,
    RuleActivationDelta,
    RuleActivationGeneration,
    RuleActivationMember,
    RuleActivationProposal,
    RuleActivationSource,
    RuleActivationStatus,
    rule_activation_generation_digest,
    rule_activation_proposal_digest,
)
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
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_upgrade import (
    RuleIdentityUpgradeApprovalV2,
    RuleIdentityUpgradeCommandV2,
    RuleIdentityUpgradeProposalV2,
    RuleReplicaCompatibilityEvidenceV2,
    RuleReviewedPolicyBaselineV2,
    RuleReviewedRevisionBaselineEntryV2,
    rule_identity_upgrade_approval_digest,
    rule_identity_upgrade_command_digest,
    rule_identity_upgrade_proposal_digest,
    rule_replica_compatibility_evidence_digest,
    rule_reviewed_policy_baseline_digest,
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
    acknowledgement_values: dict[str, RuleReplicaAcknowledgementV2]
    applied_values: dict[str, RuleReplicaAppliedV2]

    async def cohort(self, _prepare_digest: str) -> object:
        return self.cohort_value

    async def candidate_active(self) -> RuleCohortCandidateActiveV2:
        return self.candidate_value

    async def applied(
        self,
        _prepare_digest: str,
        replica_id: str,
    ) -> RuleReplicaAppliedV2 | None:
        return self.applied_values.get(replica_id)

    async def acknowledgement(
        self,
        _prepare_digest: str,
        replica_id: str,
    ) -> RuleReplicaAcknowledgementV2 | None:
        return self.acknowledgement_values.get(replica_id)


@dataclass
class _Authorizer:
    allowed: bool = True

    async def authorize_identity_upgrade(self, *_args: object, **_kwargs: object) -> bool:
        return self.allowed


@dataclass
class _Fixture:
    store: InMemoryStateStore
    legacy_ledger: StateStoreRuleActivationLedger
    upgrade: StateStoreRuleIdentityUpgrade
    baseline: RuleReviewedPolicyBaselineV2
    command: RuleIdentityUpgradeCommandV2
    authorizer: _Authorizer


async def _fixture(
    *,
    linearization_at: datetime = NOW + timedelta(seconds=7),
) -> _Fixture:
    store = InMemoryStateStore(
        linearization_clock=lambda: linearization_at,
    )
    member = RuleActivationMember(
        rule_id="rule.alpha",
        rule_version="1.0.0",
        rule_digest="a" * 64,
    )
    legacy_digest = rule_activation_generation_digest(
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest="b" * 64,
        members=(member,),
    )
    legacy = RuleActivationGeneration(
        generation_id=f"rule-activation-{legacy_digest[:32]}",
        generation_digest=legacy_digest,
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest="b" * 64,
        members=(member,),
        created_at=NOW,
    )
    await store.write_state(
        f"rule-activation:generation:{legacy.generation_id}",
        encode_rule_activation_record(
            RuleActivationRecordKind.GENERATION,
            {"generation": legacy.model_dump(mode="json")},
        ),
    )
    await store.write_state(
        "rule-activation:current",
        encode_rule_activation_record(
            RuleActivationRecordKind.POINTER,
            {
                "revision": 1,
                "generation_id": legacy.generation_id,
                "generation_digest": legacy.generation_digest,
                "previous_generation_digest": None,
            },
        ),
    )
    definition_digest = _digest("d")
    policy_identity_digest = _digest("e")
    revision = RuleRevisionIdentityRef(
        rule_id=member.rule_id,
        rule_version=member.rule_version,
        revision_digest=canonical_digest(
            {
                "rule_id": member.rule_id,
                "rule_version": member.rule_version,
                "definition_digest": definition_digest,
                "policy_identity_digest": policy_identity_digest,
            }
        ),
    )
    context = build_rule_activation_identity_context_v2(
        catalog_revisions=(revision,),
        profile_id=legacy.profile_id,
        profile_version=legacy.profile_version,
        active_members=(revision,),
    )
    baseline_entry = RuleReviewedRevisionBaselineEntryV2(
        legacy_member=member,
        revision=revision,
        definition_digest=definition_digest,
        policy_identity_digest=policy_identity_digest,
    )
    baseline_values = {
        "release_id": "release-1",
        "reviewed_source_revision": "f" * 40,
        "revision_registry_root": _digest("1"),
        "entries": (baseline_entry,),
        "reviewed_at": NOW,
    }
    baseline = RuleReviewedPolicyBaselineV2(
        **baseline_values,
        baseline_digest=rule_reviewed_policy_baseline_digest(**baseline_values),
    )
    replica = RuleReplicaIdentity(
        replica_id="replica-a",
        principal_id="principal-a",
        release_id=baseline.release_id,
        startup_epoch="epoch-a",
        serving_lease_id="lease-a",
        serving_lease_expires_at=NOW + timedelta(minutes=10),
    )
    cohort = build_rule_cohort_prepare_v2(
        generation=context.generation,
        serving_inventory_digest=_digest("2"),
        revision_registry_root=baseline.revision_registry_root,
        catalog_manifest_digest=context.catalog_manifest.manifest_digest,
        replicas=(replica,),
        prepared_at=NOW + timedelta(seconds=1),
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
        "write_schema_version": "1.0.0",
        "disposition": RuleReplicaDisposition.ACKNOWLEDGED,
        "reason": "dual-read verified",
        "authentication_receipt_digest": _digest("8"),
        "observed_at": NOW + timedelta(seconds=3),
    }
    acknowledgement = RuleReplicaAcknowledgementV2(
        **acknowledgement_values,
        acknowledgement_digest=rule_replica_acknowledgement_digest(**acknowledgement_values),
    )
    candidate = RuleCohortCandidateActiveV2(
        prepare_digest=cohort.prepare_digest,
        generation_digest=cohort.generation.generation_digest,
        acknowledgement_set_digest=rule_acknowledgement_set_digest((acknowledgement,)),
        activated_at=NOW + timedelta(seconds=2),
    )
    applied = RuleReplicaAppliedV2(
        prepare_digest=cohort.prepare_digest,
        acknowledgement_set_digest=candidate.acknowledgement_set_digest,
        replica_id=replica.replica_id,
        principal_id=replica.principal_id,
        release_id=replica.release_id,
        startup_epoch=replica.startup_epoch,
        serving_lease_id=replica.serving_lease_id,
        generation_digest=cohort.generation.generation_digest,
        applied_at=NOW + timedelta(seconds=3),
    )
    signed_manifest_digest = _digest("4")
    await store.write_state(
        "rule-activation:manifest-nonce:" + ("5" * 64),
        {
            "schema_version": "1.0.0",
            "manifest_digest": signed_manifest_digest,
            "release_id": baseline.release_id,
            "target_generation_id": context.generation.generation_id,
            "target_generation_digest": context.generation.generation_digest,
            "profile_id": context.profile_snapshot.profile_id,
            "profile_version": context.profile_snapshot.profile_version,
            "catalog_manifest_digest": context.catalog_manifest.manifest_digest,
            "revision_registry_root": baseline.revision_registry_root,
            "members": [revision.model_dump(mode="json")],
        },
    )
    proposal_values = {
        "source_generation_id": legacy.generation_id,
        "source_generation_digest": legacy.generation_digest,
        "target_identity": context,
        "signed_manifest_digest": signed_manifest_digest,
        "release_id": baseline.release_id,
        "policy_baseline_digest": baseline.baseline_digest,
        "cohort_prepare_digest": cohort.prepare_digest,
        "proposed_by": "requester-a",
        "proposed_at": NOW + timedelta(seconds=4),
    }
    proposal = RuleIdentityUpgradeProposalV2(
        **proposal_values,
        proposal_digest=rule_identity_upgrade_proposal_digest(**proposal_values),
    )
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("6"),
        "approval_profile_digest": _digest("7"),
        "requester_id": proposal.proposed_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=5),
    }
    approval = RuleIdentityUpgradeApprovalV2(
        **approval_values,
        approval_digest=rule_identity_upgrade_approval_digest(**approval_values),
    )
    compatibility_values = {
        "replica": replica,
        "supported_read_schema_versions": ("1.0.0", "2.0.0"),
        "write_schema_version": "1.0.0",
        "signed_manifest_digest": signed_manifest_digest,
        "verifier_principal_id": replica.principal_id,
        "authentication_receipt_digest": acknowledgement.authentication_receipt_digest,
        "verified_at": NOW + timedelta(seconds=3),
    }
    compatibility = RuleReplicaCompatibilityEvidenceV2(
        **compatibility_values,
        evidence_digest=rule_replica_compatibility_evidence_digest(**compatibility_values),
    )
    command_values = {
        "proposal": proposal,
        "approval": approval,
        "compatibility_evidence": (compatibility,),
        "commanded_at": NOW + timedelta(seconds=6),
    }
    command = RuleIdentityUpgradeCommandV2(
        **command_values,
        command_digest=rule_identity_upgrade_command_digest(**command_values),
    )
    evidence = _CohortEvidence(
        cohort_value=cohort,
        candidate_value=candidate,
        acknowledgement_values={replica.replica_id: acknowledgement},
        applied_values={replica.replica_id: applied},
    )
    authorizer = _Authorizer()
    legacy_ledger = StateStoreRuleActivationLedger(store=store)
    upgrade = StateStoreRuleIdentityUpgrade(
        store=store,
        legacy_ledger=legacy_ledger,
        cohort_ledger=cast(StateStoreRuleActivationCohort, evidence),
        authorizer=cast(RuleIdentityUpgradeAuthorizer, authorizer),
    )
    return _Fixture(store, legacy_ledger, upgrade, baseline, command, authorizer)


async def test_upgrade_atomically_fences_v1_and_installs_v2_authority() -> None:
    fixture = await _fixture()

    pointer = await fixture.upgrade.apply(fixture.command, baseline=fixture.baseline)
    replay = await fixture.upgrade.apply(fixture.command, baseline=fixture.baseline)
    frozen_v1 = await fixture.store.read_state("rule-activation:current")

    assert replay == pointer
    assert frozen_v1 is not None
    assert frozen_v1["v2_authoritative"] is True
    assert frozen_v1["v2_pointer_digest"] == pointer.pointer_digest
    assert await fixture.upgrade.current_authority_pointer() == pointer
    assert await fixture.store.verify_chain()


async def test_upgrade_fence_rejects_later_v1_writes() -> None:
    fixture = await _fixture()
    await fixture.upgrade.apply(fixture.command, baseline=fixture.baseline)
    generation = await fixture.legacy_ledger.current_generation()
    assert generation is not None
    proposal_values = {
        "idempotency_key": "post-v2-write",
        "expected_generation_digest": generation.generation_digest,
        "source": RuleActivationSource.DIRECT,
        "source_ref": "operator-request:post-v2-write",
        "source_digest": "9" * 64,
        "requested_by": "requester-b",
        "requested_at": NOW + timedelta(seconds=7),
        "reason": "Attempt a legacy write after the v2 cutover.",
        "changes": (RuleActivationDelta(rule_id="rule.alpha", enabled=True),),
    }
    proposal_digest = rule_activation_proposal_digest(**proposal_values)
    proposal = RuleActivationProposal(
        request_id=f"rule-activation-request-{proposal_digest[:32]}",
        **proposal_values,
    )
    command = RuleActivationCommand(
        proposal=proposal,
        approval=RuleActivationApproval(
            proposal_digest=proposal.proposal_digest,
            approver_ids=("approver-c",),
            approved_at=NOW + timedelta(seconds=8),
            approval_ref="approval:post-v2-write",
        ),
        generation=generation,
        commanded_at=NOW + timedelta(seconds=8),
    )

    result = await fixture.legacy_ledger.apply(command)

    assert result.status is RuleActivationStatus.REJECTED
    assert result.failure_reason == "version2_activation_is_authoritative"


async def test_startup_readback_never_originates_v2_authority() -> None:
    fixture = await _fixture()

    assert await fixture.upgrade.current_authority_pointer() is None
    assert await fixture.store.read_state("rule-activation-v2:current") is None


async def test_upgrade_rejects_non_authoritative_approval() -> None:
    fixture = await _fixture()
    fixture.authorizer.allowed = False

    with pytest.raises(RuleIdentityUpgradeConflictError, match="not authoritative"):
        await fixture.upgrade.apply(fixture.command, baseline=fixture.baseline)

    assert await fixture.store.read_state("rule-activation-v2:current") is None


async def test_upgrade_rechecks_serving_lease_at_linearization() -> None:
    fixture = await _fixture(linearization_at=NOW + timedelta(minutes=10))

    with pytest.raises(RuleIdentityUpgradeConflictError, match="CAS conflict"):
        await fixture.upgrade.apply(fixture.command, baseline=fixture.baseline)

    assert await fixture.store.read_state("rule-activation-v2:current") is None


async def test_upgrade_rejects_compatibility_evidence_for_another_replica() -> None:
    fixture = await _fixture()
    evidence = fixture.command.compatibility_evidence[0]
    wrong_replica = RuleReplicaIdentity.model_validate(
        {**evidence.replica.model_dump(), "replica_id": "replica-other"}
    )
    values = {
        "replica": wrong_replica,
        "supported_read_schema_versions": evidence.supported_read_schema_versions,
        "write_schema_version": evidence.write_schema_version,
        "signed_manifest_digest": evidence.signed_manifest_digest,
        "verifier_principal_id": evidence.verifier_principal_id,
        "authentication_receipt_digest": evidence.authentication_receipt_digest,
        "verified_at": evidence.verified_at,
    }
    wrong = RuleReplicaCompatibilityEvidenceV2(
        **values,
        evidence_digest=rule_replica_compatibility_evidence_digest(**values),
    )
    command_values = {
        "proposal": fixture.command.proposal,
        "approval": fixture.command.approval,
        "compatibility_evidence": (wrong,),
        "commanded_at": fixture.command.commanded_at,
    }
    command = RuleIdentityUpgradeCommandV2(
        **command_values,
        command_digest=rule_identity_upgrade_command_digest(**command_values),
    )

    with pytest.raises(RuleIdentityUpgradeConflictError, match="exact serving-replica"):
        await fixture.upgrade.apply(command, baseline=fixture.baseline)
