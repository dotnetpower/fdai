from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai.core.rule_activation.cohort import StateStoreRuleActivationCohort
from fdai.core.rule_activation.slots import (
    RuleActivationSlotConflictError,
    StateStoreRuleActivationSlots,
)
from fdai.shared.providers.rule_revision_promotion import RuleRevisionPromotionAuthorizer
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation_cohort import (
    RuleCohortCandidateActiveV2,
    RuleReplicaAppliedV2,
    RuleReplicaIdentity,
    build_rule_cohort_prepare_v2,
)
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleDualRevisionSlotV2,
    RuleRevisionBindingV2,
    RuleRevisionPromotionApprovalV2,
    rule_dual_revision_slot_digest,
    rule_revision_binding_digest,
    rule_revision_promotion_approval_digest,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _binding(version: str, character: str, mode: RuleBindingMode) -> RuleRevisionBindingV2:
    values = {
        "binding_id": "binding-alpha",
        "revision": RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version=version,
            revision_digest=_digest(character),
        ),
        "profile_snapshot_digest": _digest("c"),
        "mode": mode,
        "promotion_evidence_digest": _digest("d") if mode is RuleBindingMode.ENFORCE else None,
    }
    return RuleRevisionBindingV2(
        **values,
        binding_digest=rule_revision_binding_digest(**values),
    )


@dataclass
class _CohortEvidence:
    cohort_value: object
    candidate_value: RuleCohortCandidateActiveV2
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


@dataclass
class _PromotionAuthorizer:
    allowed: bool = True

    async def authorize(self, _approval: object, **_kwargs: object) -> bool:
        return self.allowed


def _fixture() -> tuple[RuleDualRevisionSlotV2, _CohortEvidence]:
    revisions = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            revision_digest=_digest("a"),
        ),
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.1.0",
            revision_digest=_digest("b"),
        ),
    )
    context = build_rule_activation_identity_context_v2(
        catalog_revisions=revisions,
        profile_id="baseline",
        profile_version="1.1.0",
        active_members=(revisions[1],),
    )
    replicas = tuple(
        RuleReplicaIdentity(
            replica_id=f"replica-{suffix}",
            principal_id=f"principal-{suffix}",
            release_id="release-1",
            startup_epoch=f"epoch-{suffix}",
            serving_lease_id=f"lease-{suffix}",
            serving_lease_expires_at=NOW + timedelta(minutes=10),
        )
        for suffix in ("a", "b")
    )
    cohort = build_rule_cohort_prepare_v2(
        generation=context.generation,
        serving_inventory_digest=_digest("3"),
        revision_registry_root=_digest("4"),
        catalog_manifest_digest=context.catalog_manifest.manifest_digest,
        replicas=replicas,
        prepared_at=NOW,
    )
    candidate = RuleCohortCandidateActiveV2(
        prepare_digest=cohort.prepare_digest,
        generation_digest=cohort.generation.generation_digest,
        acknowledgement_set_digest=_digest("f"),
        activated_at=NOW + timedelta(seconds=1),
    )
    applied = {
        replica.replica_id: RuleReplicaAppliedV2(
            prepare_digest=cohort.prepare_digest,
            acknowledgement_set_digest=candidate.acknowledgement_set_digest,
            replica_id=replica.replica_id,
            principal_id=replica.principal_id,
            release_id=replica.release_id,
            startup_epoch=replica.startup_epoch,
            serving_lease_id=replica.serving_lease_id,
            generation_digest=cohort.generation.generation_digest,
            applied_at=NOW + timedelta(seconds=2),
        )
        for replica in replicas
    }
    enforcing = _binding("1.0.0", "a", RuleBindingMode.ENFORCE)
    shadow_values = {
        "binding_id": "binding-alpha",
        "revision": revisions[1],
        "profile_snapshot_digest": context.profile_snapshot.snapshot_digest,
        "mode": RuleBindingMode.SHADOW,
        "promotion_evidence_digest": None,
    }
    shadow = RuleRevisionBindingV2(
        **shadow_values,
        binding_digest=rule_revision_binding_digest(**shadow_values),
    )
    slot_values = {
        "rule_id": "rule.alpha",
        "enforcing": enforcing,
        "prepared_shadow": shadow,
        "cohort_prepare_digest": cohort.prepare_digest,
        "acknowledgement_set_digest": candidate.acknowledgement_set_digest,
        "created_at": NOW,
    }
    slot = RuleDualRevisionSlotV2(
        **slot_values,
        slot_digest=rule_dual_revision_slot_digest(**slot_values),
    )
    return slot, _CohortEvidence(cohort, candidate, applied)


def _approval(slot: RuleDualRevisionSlotV2) -> RuleRevisionPromotionApprovalV2:
    values = {
        "slot_digest": slot.slot_digest,
        "from_binding_digest": slot.enforcing.binding_digest,
        "shadow_binding_digest": slot.prepared_shadow.binding_digest,
        "revision_evidence_digest": _digest("5"),
        "authority_receipt_digest": _digest("8"),
        "approval_profile_digest": _digest("6"),
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW,
    }
    return RuleRevisionPromotionApprovalV2(
        **values,
        approval_digest=rule_revision_promotion_approval_digest(**values),
    )


def _ledger(
    evidence: _CohortEvidence,
    *,
    authorizer: _PromotionAuthorizer | None = None,
) -> StateStoreRuleActivationSlots:
    return StateStoreRuleActivationSlots(
        store=InMemoryStateStore(),
        cohort_ledger=cast(StateStoreRuleActivationCohort, evidence),
        promotion_authorizer=cast(
            RuleRevisionPromotionAuthorizer,
            authorizer or _PromotionAuthorizer(),
        ),
    )


async def test_move_candidate_is_derived_from_cohort_and_approval() -> None:
    slot, evidence = _fixture()
    ledger = _ledger(evidence)
    await ledger.retain_slot(slot)

    candidate = await ledger.build_and_retain_move_candidate(
        slot_digest=slot.slot_digest,
        approval=_approval(slot),
        commanded_at=NOW + timedelta(seconds=3),
    )
    observed = await ledger.build_evaluation_evidence(
        slot_digest=slot.slot_digest,
        mode=RuleBindingMode.SHADOW,
        evaluation_receipt_digest=_digest("7"),
    )

    assert candidate.applied_replica_ids == ("replica-a", "replica-b")
    assert candidate.target_enforcing.mode is RuleBindingMode.ENFORCE
    assert (
        candidate.target_enforcing.promotion_evidence_digest == candidate.promotion_approval_digest
    )
    assert observed.binding_digest == slot.prepared_shadow.binding_digest


async def test_missing_applied_or_mismatched_approval_blocks_move() -> None:
    slot, evidence = _fixture()
    evidence.applied_values.pop("replica-b")
    ledger = _ledger(evidence)
    await ledger.retain_slot(slot)

    with pytest.raises(RuleActivationSlotConflictError, match="every cohort replica"):
        await ledger.build_and_retain_move_candidate(
            slot_digest=slot.slot_digest,
            approval=_approval(slot),
            commanded_at=NOW + timedelta(seconds=3),
        )

    _, complete_evidence = _fixture()
    complete = _ledger(complete_evidence)
    await complete.retain_slot(slot)
    approval = _approval(slot).model_copy(update={"shadow_binding_digest": _digest("9")})
    with pytest.raises(RuleActivationSlotConflictError, match="does not match"):
        await complete.build_and_retain_move_candidate(
            slot_digest=slot.slot_digest,
            approval=approval,
            commanded_at=NOW + timedelta(seconds=3),
        )


async def test_authoritative_approval_and_string_mode_are_enforced() -> None:
    slot, evidence = _fixture()
    denied = _ledger(evidence, authorizer=_PromotionAuthorizer(allowed=False))
    await denied.retain_slot(slot)

    with pytest.raises(RuleActivationSlotConflictError, match="not authoritative"):
        await denied.build_and_retain_move_candidate(
            slot_digest=slot.slot_digest,
            approval=_approval(slot),
            commanded_at=NOW + timedelta(seconds=3),
        )

    allowed = _ledger(evidence)
    await allowed.retain_slot(slot)
    observed = await allowed.build_evaluation_evidence(
        slot_digest=slot.slot_digest,
        mode="enforce",
        evaluation_receipt_digest=_digest("7"),
    )
    assert observed.binding_digest == slot.enforcing.binding_digest
