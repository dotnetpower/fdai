"""Fail-closed readiness boundary for independently verified evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    LiveEvidenceClaimRequirement,
    assess_live_evidence_claim,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    expected_verification_subjects,
)

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)


class DecisionEvidenceReadinessReason(StrEnum):
    """Why evidence is or is not eligible at a readiness boundary."""

    VERIFIED = "verified"
    PREFLIGHT_REJECTED = "preflight_rejected"
    VERIFIER_UNAVAILABLE = "verifier_unavailable"
    VERIFIER_FAILED = "verifier_failed"
    UNTRUSTED_VERIFIER = "untrusted_verifier"
    BUNDLE_MISMATCH = "bundle_mismatch"
    PROOF_MISMATCH = "proof_mismatch"
    PROOF_NOT_CURRENT = "proof_not_current"
    SELF_VERIFICATION = "self_verification"


@dataclass(frozen=True, slots=True)
class DecisionEvidenceReadinessResult:
    """Sanitized eligibility result with no execution or promotion authority."""

    eligible: bool
    reason: DecisionEvidenceReadinessReason
    receipt_digest: str
    verification_bundle_digest: str | None = None
    rejection_details: tuple[str, ...] = ()
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority or self.promotion_authority:
            raise ValueError("decision evidence readiness MUST NOT grant authority")
        if self.eligible != (self.reason is DecisionEvidenceReadinessReason.VERIFIED):
            raise ValueError("decision evidence readiness eligibility mismatched its reason")


class DecisionEvidenceReadinessGate:
    """Authenticate and independently read back evidence before readiness use."""

    def __init__(
        self,
        *,
        registry: DecisionEvidenceVerifierRegistry,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("decision evidence verification timeout MUST be in (0, 30]")
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def evaluate(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        requirement: LiveEvidenceClaimRequirement,
        *,
        evaluated_at: datetime,
    ) -> DecisionEvidenceReadinessResult:
        """Return eligible only after preflight and five independent proofs."""

        normalized_at = _aware_utc(evaluated_at)
        preflight = assess_live_evidence_claim(
            receipt,
            requirement,
            evaluated_at=normalized_at,
        )
        if not preflight.eligible_for_verification:
            return _rejected(
                receipt,
                DecisionEvidenceReadinessReason.PREFLIGHT_REJECTED,
                details=tuple(reason.value for reason in preflight.rejection_reasons),
            )
        binding = self._registry.resolve(
            authority_class=receipt.authority_class,
            method_id=receipt.method_id,
        )
        if binding is None:
            return _rejected(receipt, DecisionEvidenceReadinessReason.VERIFIER_UNAVAILABLE)
        if not binding.active_at(normalized_at):
            return _rejected(receipt, DecisionEvidenceReadinessReason.UNTRUSTED_VERIFIER)
        if binding.verifier_id in {receipt.source_identity, receipt.producer_id}:
            return _rejected(receipt, DecisionEvidenceReadinessReason.SELF_VERIFICATION)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                bundle = await binding.verifier.verify(
                    receipt,
                    trust_anchor_id=binding.trust_anchor_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - provider failures are bounded rejection evidence
            return _rejected(receipt, DecisionEvidenceReadinessReason.VERIFIER_FAILED)
        return _evaluate_bundle(
            receipt,
            bundle=bundle,
            binding=binding,
            evaluated_at=normalized_at,
        )


def _evaluate_bundle(
    receipt: DecisionCriticalEvidenceReceipt,
    *,
    bundle: DecisionEvidenceVerificationBundle,
    binding: DecisionEvidenceVerifierBinding,
    evaluated_at: datetime,
) -> DecisionEvidenceReadinessResult:
    if (
        bundle.receipt_digest != receipt.receipt_digest
        or bundle.verifier_id != binding.verifier_id
        or bundle.verifier_version != binding.verifier_version
        or bundle.trust_anchor_id != binding.trust_anchor_id
    ):
        return _rejected(receipt, DecisionEvidenceReadinessReason.BUNDLE_MISMATCH)
    if not bundle.verified_at <= evaluated_at <= bundle.valid_until:
        return _rejected(receipt, DecisionEvidenceReadinessReason.PROOF_NOT_CURRENT)
    expected = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    actual = {proof.kind: proof.subject_digest for proof in bundle.proofs}
    if actual != expected:
        return _rejected(receipt, DecisionEvidenceReadinessReason.PROOF_MISMATCH)
    return DecisionEvidenceReadinessResult(
        eligible=True,
        reason=DecisionEvidenceReadinessReason.VERIFIED,
        receipt_digest=receipt.receipt_digest,
        verification_bundle_digest=bundle.bundle_digest,
    )


def _rejected(
    receipt: DecisionCriticalEvidenceReceipt,
    reason: DecisionEvidenceReadinessReason,
    *,
    details: tuple[str, ...] = (),
) -> DecisionEvidenceReadinessResult:
    return DecisionEvidenceReadinessResult(
        eligible=False,
        reason=reason,
        receipt_digest=receipt.receipt_digest,
        rejection_details=details,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision evidence readiness time MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "DecisionEvidenceReadinessGate",
    "DecisionEvidenceReadinessReason",
    "DecisionEvidenceReadinessResult",
]
