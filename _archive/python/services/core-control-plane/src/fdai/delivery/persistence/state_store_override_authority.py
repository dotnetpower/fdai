"""Durable Var-approval verifier for operator override promotions."""

from __future__ import annotations

from fdai.delivery.promotion_attestation import (
    attestation_from_json,
    promotion_attestation_digest,
)
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceChangeClass,
    validate_governance_review,
)
from fdai.shared.providers.direct_api import DirectApiPreconditionError
from fdai.shared.providers.state_store import StateStore


class StateStoreOperatorOverrideAuthorityVerifier:
    """Verify an override promotion against the durable Var approval attestation."""

    def __init__(
        self,
        store: StateStore,
    ) -> None:
        self._store = store

    async def verify_override(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        gate_evidence_digest: str,
        approval_receipt_digest: str,
        operator_principal: str,
    ) -> bool:
        del action_type_version, action_type_digest
        raw = await self._store.find_state(
            "governance-promotion-attestation:",
            field="approval_receipt_digest",
            value=approval_receipt_digest,
        )
        if raw is None or raw.get("state") not in {"reserved", "consumed"}:
            return False
        attestation_raw = raw.get("attestation")
        if not isinstance(attestation_raw, dict):
            return False
        try:
            attestation = attestation_from_json(attestation_raw)
            decision = validate_governance_review(attestation.review)
        except (DirectApiPreconditionError, ValueError):
            return False
        if promotion_attestation_digest(attestation) != approval_receipt_digest:
            return False
        operator = operator_principal.casefold()
        return (
            attestation.action_type_id == action_type
            and attestation.evidence_digest == gate_evidence_digest
            and decision.change_class is GovernanceChangeClass.OPERATOR_OVERRIDE_PROMOTION
            and decision.allowed
            and decision.satisfied_quorum >= decision.required_quorum
            and (
                operator in decision.counted_approver_oids
                or operator == (decision.operator_principal or "").casefold()
            )
        )


__all__ = ["StateStoreOperatorOverrideAuthorityVerifier"]
