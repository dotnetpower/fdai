"""Deterministic first-stage checks for completed chat answers."""

from __future__ import annotations

from fdai.core.conversation_assurance.models import (
    AssuranceVerdict,
    DeterministicAssessment,
    TurnAssessmentInput,
)

_FINAL_VERIFICATION_STATES = frozenset({"verified", "consistent", "corrected"})


def assess_deterministically(turn: TurnAssessmentInput) -> DeterministicAssessment:
    """Return a decisive result when existing terminal evidence is sufficient."""

    if turn.failed_claim_ids:
        return DeterministicAssessment(
            verdict=AssuranceVerdict.FAIL,
            reasons=("unsupported_atomic_claim",),
        )
    if turn.verification_status == "unverified":
        reason = "verification_failed" if turn.checks_total else "evidence_unavailable"
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
        return DeterministicAssessment(
            verdict=AssuranceVerdict.PASS,
            reasons=("deterministic_answer_verified",),
        )
    return DeterministicAssessment(verdict=None, reasons=("semantic_review_required",))


__all__ = ["assess_deterministically"]
