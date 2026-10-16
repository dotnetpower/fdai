"""Dormant durable dual-revision slots and binding-move candidates."""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleBindingMoveCandidateV2,
    RuleDualRevisionSlotV2,
    RuleRevisionBindingV2,
    RuleRevisionEvaluationEvidenceV2,
    RuleRevisionPromotionApprovalV2,
    rule_binding_move_candidate_digest,
    rule_revision_binding_digest,
)

from fdai.core.rule_activation.cohort import StateStoreRuleActivationCohort
from fdai.shared.providers.rule_revision_promotion import RuleRevisionPromotionAuthorizer
from fdai.shared.providers.state_store import StateStore

_SLOT_PREFIX = "rule-activation-v2:slot:"
_MOVE_PREFIX = "rule-activation-v2:binding-move:"


class RuleActivationSlotConflictError(RuntimeError):
    """Raised when immutable slot or move identities conflict."""


class StateStoreRuleActivationSlots:
    """Persist inert slots and move candidates without changing enforcement."""

    def __init__(
        self,
        *,
        store: StateStore,
        cohort_ledger: StateStoreRuleActivationCohort,
        promotion_authorizer: RuleRevisionPromotionAuthorizer,
    ) -> None:
        self._store = store
        self._cohort_ledger = cohort_ledger
        self._promotion_authorizer = promotion_authorizer

    async def retain_slot(self, slot: RuleDualRevisionSlotV2) -> None:
        key = _SLOT_PREFIX + slot.slot_digest.removeprefix("sha256:")
        value = slot.model_dump(mode="json")
        if await self._store.write_state_if_absent(key, value):
            return
        if await self._store.read_state(key) != value:
            raise RuleActivationSlotConflictError("Rule dual-revision slot identity conflict")

    async def build_and_retain_move_candidate(
        self,
        *,
        slot_digest: str,
        approval: RuleRevisionPromotionApprovalV2,
        commanded_at: datetime,
    ) -> RuleBindingMoveCandidateV2:
        slot = await self.slot(slot_digest)
        if (
            approval.slot_digest != slot.slot_digest
            or approval.from_binding_digest != slot.enforcing.binding_digest
            or approval.shadow_binding_digest != slot.prepared_shadow.binding_digest
        ):
            raise RuleActivationSlotConflictError("Rule promotion approval does not match the slot")
        cohort = await self._cohort_ledger.cohort(slot.cohort_prepare_digest)
        if (
            slot.prepared_shadow.profile_snapshot_digest
            != cohort.generation.profile_snapshot_digest
            or slot.prepared_shadow.revision not in cohort.generation.members
        ):
            raise RuleActivationSlotConflictError(
                "Rule prepared shadow does not match the cohort generation"
            )
        if not await self._promotion_authorizer.authorize(
            approval,
            slot=slot,
            target_revision=slot.prepared_shadow.revision,
        ):
            raise RuleActivationSlotConflictError(
                "Rule revision promotion approval is not authoritative"
            )
        candidate_active = await self._cohort_ledger.candidate_active()
        if (
            candidate_active.prepare_digest != cohort.prepare_digest
            or candidate_active.acknowledgement_set_digest != slot.acknowledgement_set_digest
            or candidate_active.generation_digest != cohort.generation.generation_digest
        ):
            raise RuleActivationSlotConflictError(
                "Rule slot does not match candidate-active cohort"
            )
        required_replica_ids = tuple(replica.replica_id for replica in cohort.replicas)
        applied_replica_ids: list[str] = []
        for replica_id in required_replica_ids:
            applied = await self._cohort_ledger.applied(cohort.prepare_digest, replica_id)
            if (
                applied is None
                or applied.acknowledgement_set_digest != candidate_active.acknowledgement_set_digest
                or applied.generation_digest != candidate_active.generation_digest
            ):
                raise RuleActivationSlotConflictError(
                    "Rule binding move requires every cohort replica applied"
                )
            applied_replica_ids.append(replica_id)
        target = RuleRevisionBindingV2(
            binding_id=slot.prepared_shadow.binding_id,
            revision=slot.prepared_shadow.revision,
            profile_snapshot_digest=slot.prepared_shadow.profile_snapshot_digest,
            mode=RuleBindingMode.ENFORCE,
            promotion_evidence_digest=approval.approval_digest,
            binding_digest=rule_revision_binding_digest(
                binding_id=slot.prepared_shadow.binding_id,
                revision=slot.prepared_shadow.revision,
                profile_snapshot_digest=slot.prepared_shadow.profile_snapshot_digest,
                mode=RuleBindingMode.ENFORCE,
                promotion_evidence_digest=approval.approval_digest,
            ),
        )
        applied_ids = tuple(applied_replica_ids)
        candidate = RuleBindingMoveCandidateV2(
            slot_digest=slot.slot_digest,
            from_binding_digest=slot.enforcing.binding_digest,
            shadow_binding_digest=slot.prepared_shadow.binding_digest,
            target_enforcing=target,
            acknowledgement_set_digest=slot.acknowledgement_set_digest,
            applied_replica_ids=applied_ids,
            required_replica_ids=required_replica_ids,
            revision_evidence_digest=approval.revision_evidence_digest,
            promotion_approval_digest=approval.approval_digest,
            commanded_at=commanded_at,
            command_digest=rule_binding_move_candidate_digest(
                slot_digest=slot.slot_digest,
                from_binding_digest=slot.enforcing.binding_digest,
                shadow_binding_digest=slot.prepared_shadow.binding_digest,
                target_enforcing=target,
                acknowledgement_set_digest=slot.acknowledgement_set_digest,
                applied_replica_ids=applied_ids,
                required_replica_ids=required_replica_ids,
                revision_evidence_digest=approval.revision_evidence_digest,
                promotion_approval_digest=approval.approval_digest,
                commanded_at=commanded_at,
            ),
        )
        key = _MOVE_PREFIX + candidate.command_digest.removeprefix("sha256:")
        value = candidate.model_dump(mode="json")
        if await self._store.write_state_if_absent(key, value):
            return candidate
        if await self._store.read_state(key) == value:
            return candidate
        else:
            raise RuleActivationSlotConflictError("Rule binding move candidate identity conflict")

    async def build_evaluation_evidence(
        self,
        *,
        slot_digest: str,
        mode: RuleBindingMode | str,
        evaluation_receipt_digest: str,
    ) -> RuleRevisionEvaluationEvidenceV2:
        """Build consistent evidence from one retained slot and selected binding."""

        slot = await self.slot(slot_digest)
        selected_mode = RuleBindingMode(mode)
        binding = (
            slot.enforcing if selected_mode is RuleBindingMode.ENFORCE else slot.prepared_shadow
        )
        return RuleRevisionEvaluationEvidenceV2(
            rule_id=slot.rule_id,
            revision_digest=binding.revision.revision_digest,
            binding_digest=binding.binding_digest,
            slot_digest=slot.slot_digest,
            mode=selected_mode,
            evaluation_receipt_digest=evaluation_receipt_digest,
        )

    async def slot(self, slot_digest: str) -> RuleDualRevisionSlotV2:
        raw = await self._store.read_state(_SLOT_PREFIX + slot_digest.removeprefix("sha256:"))
        if raw is None:
            raise RuleActivationSlotConflictError("Rule dual-revision slot is unavailable")
        return RuleDualRevisionSlotV2.model_validate(raw)


__all__ = ["RuleActivationSlotConflictError", "StateStoreRuleActivationSlots"]
