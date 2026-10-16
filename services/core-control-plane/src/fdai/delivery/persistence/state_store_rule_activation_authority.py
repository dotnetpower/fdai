"""Durable governance-attestation authority for Rule revision transitions."""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.approval_profile import ApprovalProfileRevision
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_revision_change import (
    RuleRevisionChangeApprovalV2,
    RuleRevisionChangeProposalV2,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleDualRevisionSlotV2,
    RuleRevisionPromotionApprovalV2,
)
from fdai_service_contracts.rule_activation_upgrade import (
    RuleIdentityUpgradeApprovalV2,
    RuleIdentityUpgradeProposalV2,
    RuleReviewedPolicyBaselineV2,
)

from fdai.delivery.promotion_attestation import (
    GovernancePromotionAttestation,
    attestation_from_json,
    promotion_attestation_digest,
)
from fdai.delivery.promotion_review import approval_profile_matches
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceChangeClass,
    ReviewAuthorityDecision,
    validate_governance_review,
)
from fdai.shared.providers.direct_api import DirectApiPreconditionError
from fdai.shared.providers.state_store import StateStore

_ATTESTATION_PREFIX = "governance-promotion-attestation:"


class StateStoreRuleActivationAuthority:
    """Validate Rule transition approvals from durable Var attestations."""

    def __init__(
        self,
        store: StateStore,
        *,
        active_approval_profile: ApprovalProfileRevision,
    ) -> None:
        self._store = store
        self._active_approval_profile = active_approval_profile

    async def authorize(
        self,
        approval: RuleRevisionPromotionApprovalV2,
        *,
        slot: RuleDualRevisionSlotV2,
        target_revision: RuleRevisionIdentityRef,
    ) -> bool:
        resolved = await self._resolve(approval.authority_receipt_digest)
        if resolved is None:
            return False
        attestation, decision = resolved
        return (
            _decision_matches(
                attestation,
                decision,
                approval_profile_digest=approval.approval_profile_digest,
                approver_ids=approval.approver_ids,
                original_quorum=approval.original_quorum,
                effective_quorum=approval.effective_quorum,
                approved_at=approval.approved_at,
            )
            and attestation.action_type_id == "rule-revision-promote"
            and attestation.evidence_digest == approval.revision_evidence_digest
            and attestation.idempotency_key == slot.slot_digest
            and attestation.scenario_set_version == target_revision.rule_version
            and attestation.request_fingerprint == target_revision.revision_digest
        )

    async def authorize_identity_upgrade(
        self,
        approval: RuleIdentityUpgradeApprovalV2,
        *,
        proposal: RuleIdentityUpgradeProposalV2,
        baseline: RuleReviewedPolicyBaselineV2,
    ) -> bool:
        resolved = await self._resolve(approval.authority_receipt_digest)
        if resolved is None:
            return False
        attestation, decision = resolved
        return (
            _decision_matches(
                attestation,
                decision,
                approval_profile_digest=approval.approval_profile_digest,
                approver_ids=approval.approver_ids,
                original_quorum=approval.original_quorum,
                effective_quorum=approval.effective_quorum,
                approved_at=approval.approved_at,
            )
            and attestation.action_type_id == "rule-identity-upgrade"
            and attestation.review.author.oid.casefold() == proposal.proposed_by.casefold()
            and attestation.evidence_digest == proposal.proposal_digest
            and attestation.idempotency_key == proposal.proposal_digest
            and attestation.request_fingerprint
            == proposal.target_identity.generation.generation_digest
            and attestation.scenario_set_version
            == proposal.target_identity.profile_snapshot.profile_version
            and attestation.fdai_revision == baseline.reviewed_source_revision
        )

    async def authorize_revision_change(
        self,
        approval: RuleRevisionChangeApprovalV2,
        *,
        proposal: RuleRevisionChangeProposalV2,
    ) -> bool:
        resolved = await self._resolve(approval.authority_receipt_digest)
        if resolved is None:
            return False
        attestation, decision = resolved
        return (
            _decision_matches(
                attestation,
                decision,
                approval_profile_digest=approval.approval_profile_digest,
                approver_ids=approval.approver_ids,
                original_quorum=approval.original_quorum,
                effective_quorum=approval.effective_quorum,
                approved_at=approval.approved_at,
            )
            and attestation.action_type_id == "rule-revision-change"
            and attestation.review.author.oid.casefold() == proposal.proposed_by.casefold()
            and attestation.evidence_digest == proposal.proposal_digest
            and attestation.idempotency_key == proposal.proposal_digest
            and attestation.request_fingerprint
            == proposal.identity_transition.target.generation.generation_digest
            and attestation.scenario_set_version
            == proposal.identity_transition.target.profile_snapshot.profile_version
            and attestation.fdai_revision == proposal.reviewed_source_revision
        )

    async def _resolve(
        self,
        authority_receipt_digest: str,
    ) -> tuple[GovernancePromotionAttestation, ReviewAuthorityDecision] | None:
        raw_digest = authority_receipt_digest.removeprefix("sha256:")
        raw = await self._store.find_state(
            _ATTESTATION_PREFIX,
            field="approval_receipt_digest",
            value=raw_digest,
        )
        if raw is None or raw.get("state") not in {"reserved", "consumed"}:
            return None
        attestation_raw = raw.get("attestation")
        if not isinstance(attestation_raw, dict):
            return None
        try:
            attestation = attestation_from_json(attestation_raw)
            decision = validate_governance_review(attestation.review)
        except (DirectApiPreconditionError, ValueError):
            return None
        if promotion_attestation_digest(attestation) != raw_digest:
            return None
        if not approval_profile_matches(
            attestation.review.approval_profile,
            self._active_approval_profile,
        ):
            return None
        return attestation, decision


def _decision_matches(
    attestation: GovernancePromotionAttestation,
    decision: ReviewAuthorityDecision,
    *,
    approval_profile_digest: str,
    approver_ids: tuple[str, ...],
    original_quorum: int,
    effective_quorum: int,
    approved_at: datetime,
) -> bool:
    profile = attestation.review.approval_profile
    if (
        profile is None
        or profile.policy_digest != approval_profile_digest
        or decision.change_class is not GovernanceChangeClass.ENFORCE_PROMOTION
        or not decision.allowed
        or decision.original_quorum != original_quorum
        or decision.effective_quorum != effective_quorum
        or decision.satisfied_quorum < decision.required_quorum
        or tuple(item.casefold() for item in approver_ids) != decision.counted_approver_oids
    ):
        return False
    counted = set(decision.counted_approver_oids)
    counted_times = tuple(
        item.approved_at
        for item in attestation.review.approvals
        if item.approver.oid.casefold() in counted
        and not item.dismissed
        and item.reviewed_revision == attestation.review.head_revision
    )
    return bool(counted_times) and approved_at == max(counted_times)


__all__ = ["StateStoreRuleActivationAuthority"]
