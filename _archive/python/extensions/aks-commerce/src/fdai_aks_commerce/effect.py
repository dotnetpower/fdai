"""Independent business-effect closure for a governed commerce action."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fdai_service_contracts import (
    AksCommerceAction,
    AksCommerceProjection,
    AksCommerceStatus,
)

from fdai_aks_commerce.acceptance import (
    OrderAcceptanceIntent,
    OrderAcceptanceReceiptVerifier,
    OrderAcceptanceSource,
    evaluate_order_acceptance,
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


@dataclass(frozen=True, slots=True)
class AcceptanceEffectExpectation:
    """Trusted action-owner handoff naming the exact applied scale and pre-action evidence.

    This object carries no approval or execution authority. The action owner must construct it
    from its retained admitted command and provider receipt, never from operator-supplied claims.
    """

    action_run_ref: str
    provider_receipt_ref: str
    target_ref: str
    deployment_uid: str
    replica_count: int
    applied_at: datetime
    before_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (
            self.action_run_ref,
            self.provider_receipt_ref,
            self.target_ref,
            self.deployment_uid,
            *self.before_evidence_refs,
        )
        if any(not value or len(value) > 512 for value in values):
            raise ValueError("acceptance effect requires bounded action and evidence references")
        if not 1 <= len(self.before_evidence_refs) <= 12 or len(
            set(self.before_evidence_refs)
        ) != len(self.before_evidence_refs):
            raise ValueError("acceptance effect requires distinct pre-action observations")
        if type(self.replica_count) is not int or not 1 <= self.replica_count <= 10:
            raise ValueError("acceptance effect expected replica count is invalid")
        if self.applied_at.tzinfo is None or self.applied_at.utcoffset() is None:
            raise ValueError("acceptance effect application time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AcceptanceEffectResult:
    """Read-only effect evidence, not an Incident transition or authority grant."""

    status: Literal["verified", "not_recovered", "held"]
    action_run_ref: str
    reason: str
    evidence_ref: str | None = None
    execution_authority: Literal[False] = False


async def verify_order_acceptance_effect(
    *,
    expectation: AcceptanceEffectExpectation,
    intent: OrderAcceptanceIntent,
    source: OrderAcceptanceSource,
    verifier: OrderAcceptanceReceiptVerifier,
    clock: Callable[[], datetime] | None = None,
) -> AcceptanceEffectResult:
    """Verify a later signed resource-and-order observation within a five-second read budget.

    Dependency failure and missing evidence propagate or hold; neither becomes success. This
    observer never changes a replica, retries an action, or closes its owning lifecycle record.
    """
    now = clock or (lambda: datetime.now(UTC))

    def result(
        status: Literal["verified", "not_recovered", "held"],
        reason: str,
        evidence_ref: str | None = None,
    ) -> AcceptanceEffectResult:
        return AcceptanceEffectResult(status, expectation.action_run_ref, reason, evidence_ref)

    if (
        expectation.target_ref != intent.resource_ref
        or expectation.deployment_uid != intent.deployment_uid
        or expectation.replica_count != intent.minimum_replicas
    ):
        return result("held", "action_target_mismatch")
    async with asyncio.timeout(5):
        evidence = await source.observe(intent)
        if evidence is None:
            return result("held", "observation_unavailable")
        assessment = evaluate_order_acceptance(
            intent, evidence, now=now(), window_seconds=intent.max_age_seconds
        )
        if assessment.status == "held":
            return result("held", "observation_unqualified")
        if not expectation.applied_at < evidence.observed_at or any(
            probe.observed_at <= expectation.applied_at for probe in evidence.probes
        ):
            return result("held", "observation_predates_effect")
        observation_refs = {
            evidence.kubernetes_evidence_ref,
            *(probe.evidence_ref for probe in evidence.probes),
        }
        if observation_refs.intersection(expectation.before_evidence_refs):
            return result("held", "observation_reused")
        if (
            await verifier.verify(
                verification_ref=evidence.verification_ref,
                evidence_digest=assessment.evidence_digest,
            )
            is not True
        ):
            return result("held", "observation_not_authenticated")
        refreshed = evaluate_order_acceptance(
            intent, evidence, now=now(), window_seconds=intent.max_age_seconds
        )
        if refreshed.status == "held":
            return result("held", "observation_expired_during_verification")
        if (
            refreshed.status != "accepting"
            or evidence.desired_replicas != expectation.replica_count
        ):
            return result(
                "not_recovered", "expected_effect_not_observed", assessment.evidence_digest
            )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "action_run_ref": expectation.action_run_ref,
                    "provider_receipt_ref": expectation.provider_receipt_ref,
                    "target_ref": expectation.target_ref,
                    "deployment_uid": expectation.deployment_uid,
                    "replica_count": expectation.replica_count,
                    "applied_at": expectation.applied_at.isoformat(),
                    "before_evidence_refs": expectation.before_evidence_refs,
                    "after_evidence_digest": assessment.evidence_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return result("verified", "resource_and_order_acceptance_observed", "sha256:" + digest)


__all__ = [
    "AcceptanceEffectExpectation",
    "AcceptanceEffectResult",
    "verify_business_effect",
    "verify_order_acceptance_effect",
]
