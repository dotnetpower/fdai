from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleBindingMoveCandidateV2,
    RuleDualRevisionSlotV2,
    RuleRevisionBindingV2,
    RuleRevisionEvaluationEvidenceV2,
    RuleRevisionPromotionApprovalV2,
    rule_binding_move_candidate_digest,
    rule_dual_revision_slot_digest,
    rule_revision_binding_digest,
    rule_revision_promotion_approval_digest,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _revision(version: str, character: str) -> RuleRevisionIdentityRef:
    return RuleRevisionIdentityRef(
        rule_id="rule.alpha",
        rule_version=version,
        revision_digest=_digest(character),
    )


def _binding(
    *,
    binding_id: str,
    revision: RuleRevisionIdentityRef,
    mode: RuleBindingMode,
) -> RuleRevisionBindingV2:
    values = {
        "binding_id": binding_id,
        "revision": revision,
        "profile_snapshot_digest": _digest("c"),
        "mode": mode,
        "promotion_evidence_digest": _digest("d") if mode is RuleBindingMode.ENFORCE else None,
    }
    return RuleRevisionBindingV2(
        **values,
        binding_digest=rule_revision_binding_digest(**values),
    )


def _slot() -> RuleDualRevisionSlotV2:
    enforcing = _binding(
        binding_id="binding-alpha",
        revision=_revision("1.0.0", "a"),
        mode=RuleBindingMode.ENFORCE,
    )
    shadow = _binding(
        binding_id="binding-alpha",
        revision=_revision("1.1.0", "b"),
        mode=RuleBindingMode.SHADOW,
    )
    values = {
        "rule_id": "rule.alpha",
        "enforcing": enforcing,
        "prepared_shadow": shadow,
        "cohort_prepare_digest": _digest("e"),
        "acknowledgement_set_digest": _digest("f"),
        "created_at": NOW,
    }
    return RuleDualRevisionSlotV2(
        **values,
        slot_digest=rule_dual_revision_slot_digest(**values),
    )


def _approval(slot: RuleDualRevisionSlotV2) -> RuleRevisionPromotionApprovalV2:
    values = {
        "slot_digest": slot.slot_digest,
        "from_binding_digest": slot.enforcing.binding_digest,
        "shadow_binding_digest": slot.prepared_shadow.binding_digest,
        "revision_evidence_digest": _digest("2"),
        "approval_profile_digest": _digest("3"),
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW,
    }
    return RuleRevisionPromotionApprovalV2(
        **values,
        approval_digest=rule_revision_promotion_approval_digest(**values),
    )


def test_dual_revision_slot_pins_old_enforce_and_new_shadow() -> None:
    slot = _slot()
    evidence = RuleRevisionEvaluationEvidenceV2(
        rule_id=slot.rule_id,
        revision_digest=slot.prepared_shadow.revision.revision_digest,
        binding_digest=slot.prepared_shadow.binding_digest,
        slot_digest=slot.slot_digest,
        mode=RuleBindingMode.SHADOW,
        evaluation_receipt_digest=_digest("1"),
    )

    assert slot.enforcing.mode is RuleBindingMode.ENFORCE
    assert evidence.revision_digest == slot.prepared_shadow.revision.revision_digest
    values = {
        "binding_id": "invalid",
        "revision": _revision("1.0.0", "a"),
        "profile_snapshot_digest": _digest("c"),
        "mode": RuleBindingMode.SHADOW,
        "promotion_evidence_digest": _digest("d"),
    }
    with pytest.raises(ValueError, match="promotion evidence"):
        RuleRevisionBindingV2(
            **values,
            binding_digest=rule_revision_binding_digest(**values),
        )


def test_binding_move_requires_every_replica_applied() -> None:
    slot = _slot()
    approval = _approval(slot)
    target_values = {
        "binding_id": slot.prepared_shadow.binding_id,
        "revision": slot.prepared_shadow.revision,
        "profile_snapshot_digest": slot.prepared_shadow.profile_snapshot_digest,
        "mode": RuleBindingMode.ENFORCE,
        "promotion_evidence_digest": approval.approval_digest,
    }
    target = RuleRevisionBindingV2(
        **target_values,
        binding_digest=rule_revision_binding_digest(**target_values),
    )
    values = {
        "slot_digest": slot.slot_digest,
        "from_binding_digest": slot.enforcing.binding_digest,
        "shadow_binding_digest": slot.prepared_shadow.binding_digest,
        "target_enforcing": target,
        "acknowledgement_set_digest": slot.acknowledgement_set_digest,
        "applied_replica_ids": ("replica-a",),
        "required_replica_ids": ("replica-a", "replica-b"),
        "revision_evidence_digest": approval.revision_evidence_digest,
        "promotion_approval_digest": approval.approval_digest,
        "commanded_at": NOW,
    }

    with pytest.raises(ValueError, match="every cohort replica"):
        RuleBindingMoveCandidateV2(
            **values,
            command_digest=rule_binding_move_candidate_digest(**values),
        )


def test_slot_rejects_different_logical_binding_ids() -> None:
    slot = _slot()
    shadow = _binding(
        binding_id="another-binding",
        revision=slot.prepared_shadow.revision,
        mode=RuleBindingMode.SHADOW,
    )
    values = {
        "rule_id": slot.rule_id,
        "enforcing": slot.enforcing,
        "prepared_shadow": shadow,
        "cohort_prepare_digest": slot.cohort_prepare_digest,
        "acknowledgement_set_digest": slot.acknowledgement_set_digest,
        "created_at": NOW,
    }

    with pytest.raises(ValueError, match="binding roles"):
        RuleDualRevisionSlotV2(
            **values,
            slot_digest=rule_dual_revision_slot_digest(**values),
        )
