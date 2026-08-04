"""Deterministic first-stage checks for completed chat answers."""

from __future__ import annotations

from fdai.core.conversation_assurance.models import (
    AssuranceVerdict,
    DeterministicAssessment,
    TurnAssessmentInput,
)

_FINAL_VERIFICATION_STATES = frozenset({"verified", "consistent", "corrected"})
_UNAVAILABLE_AUTHORITIES = frozenset({"none", "unknown", "unavailable", "unverified"})


def assess_deterministically(turn: TurnAssessmentInput) -> DeterministicAssessment:
    """Return a decisive result when existing terminal evidence is sufficient."""

    if turn.failed_claim_ids:
        reasons = ["unsupported_atomic_claim"]
        if turn.verification_status == "unverified":
            reasons.append(f"verification_failed:{turn.verification_reason_code}")
        return DeterministicAssessment(
            verdict=AssuranceVerdict.FAIL,
            reasons=tuple(reasons),
        )
    if turn.verification_status == "unverified":
        prefix = "verification_failed" if turn.checks_total else "evidence_unavailable"
        reason = f"{prefix}:{turn.verification_reason_code}"
        verdict = AssuranceVerdict.FAIL if turn.checks_total else AssuranceVerdict.INCONCLUSIVE
        return DeterministicAssessment(verdict=verdict, reasons=(reason,))
    if turn.checks_completed < turn.checks_total:
        return DeterministicAssessment(
            verdict=AssuranceVerdict.INCONCLUSIVE,
            reasons=("verification_incomplete",),
        )
    if turn.verification_status not in _FINAL_VERIFICATION_STATES:
        return DeterministicAssessment(
            verdict=AssuranceVerdict.INCONCLUSIVE,
            reasons=("verification_status_unknown",),
        )
    if turn.deterministic_answer and turn.checks_total > 0:
        if not turn.evidence_refs:
            return DeterministicAssessment(
                verdict=AssuranceVerdict.INCONCLUSIVE,
                reasons=("evidence_manifest_empty",),
            )
        if turn.verification_authority.casefold() in _UNAVAILABLE_AUTHORITIES:
            return DeterministicAssessment(
                verdict=AssuranceVerdict.INCONCLUSIVE,
                reasons=("verification_authority_unavailable",),
            )
        return DeterministicAssessment(
            verdict=AssuranceVerdict.PASS,
            reasons=("deterministic_answer_verified",),
        )
    return DeterministicAssessment(verdict=None, reasons=("semantic_review_required",))


__all__ = ["assess_deterministically"]
