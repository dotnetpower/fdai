"""Shared review-attestation checks for governance promotion dispatch."""

from __future__ import annotations

from fdai_service_contracts.approval_profile import ApprovalProfileRevision

from fdai.delivery.promotion_attestation import (
    GovernancePromotionAttestation,
    promotion_attestation_digest,
)
from fdai.delivery.promotion_override import (
    OVERRIDE_PROMOTION_ACTION_TYPE,
    override_promotion_arguments,
)
from fdai.rule_catalog.schema.governance_review_authority import GovernanceChangeClass
from fdai.shared.providers.direct_api import DirectApiPreconditionError, DirectApiRequest


def approval_profile_matches(
    attested: ApprovalProfileRevision | None,
    active: ApprovalProfileRevision | None,
) -> bool:
    if attested is None or active is None:
        return attested is None and active is None
    return attested.as_audit_dict() == active.as_audit_dict()


def attestation_matches_override_receipt(
    request: DirectApiRequest,
    attestation: GovernancePromotionAttestation,
) -> bool:
    if request.action_type_name != OVERRIDE_PROMOTION_ACTION_TYPE:
        return True
    if attestation.review.change_class is not GovernanceChangeClass.OPERATOR_OVERRIDE_PROMOTION:
        return False
    try:
        args = override_promotion_arguments(request.arguments)
    except DirectApiPreconditionError:
        return False
    return args["approval_receipt_digest"] == promotion_attestation_digest(attestation)


__all__ = ["approval_profile_matches", "attestation_matches_override_receipt"]
