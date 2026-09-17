"""Independent business-effect closure for a governed commerce action."""

from __future__ import annotations

from fdai_service_contracts import (
    AksCommerceAction,
    AksCommerceProjection,
    AksCommerceStatus,
)

_DEGRADED = frozenset(
    {
        AksCommerceStatus.CATALOG_UNAVAILABLE,
        AksCommerceStatus.DEAD_LETTER_GROWTH,
        AksCommerceStatus.DEPENDENCY_PRESSURE,
        AksCommerceStatus.DEPLOYMENT_REGRESSION,
        AksCommerceStatus.ORDER_BACKLOG,
    }
)


def verify_business_effect(
    *,
    action_type: str,
    target_ref: str,
    action_run_ref: str,
    before: AksCommerceProjection,
    after: AksCommerceProjection,
) -> AksCommerceAction:
    """Close one action only from a later complete independent observation."""

    if before.service_id != after.service_id:
        raise ValueError("business-effect observations must target the same service")
    if after.observed_at <= before.observed_at:
        raise ValueError("business-effect observation must follow the pre-action assessment")
    if before.status not in _DEGRADED:
        raise ValueError("business-effect verification requires a degraded pre-action state")
    if not before.complete or not after.complete:
        raise ValueError("business-effect verification requires complete observations")
    if set(before.evidence_refs) & set(after.evidence_refs):
        raise ValueError("business-effect verification requires distinct observation evidence")
    verified = after.status in {AksCommerceStatus.HEALTHY, AksCommerceStatus.RECOVERED}
    return AksCommerceAction(
        action_type=action_type,
        state="completed" if verified else "failed",
        target_ref=target_ref,
        action_run_ref=action_run_ref,
        effect_verified=verified,
        effect_evidence_ref=after.assessment_id,
    )


__all__ = ["verify_business_effect"]
