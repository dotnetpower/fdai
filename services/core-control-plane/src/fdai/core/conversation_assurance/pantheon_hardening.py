"""Classify Pantheon diagnostic failures before any isolated hardening attempt."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.core.conversation_assurance.pantheon_scorecard import (
    PantheonDiagnosticVerdict,
    PantheonRubric,
    PantheonTurnDiagnostic,
)


class PantheonWeakness(StrEnum):
    PROMPT_CONTRACT = "prompt_contract"
    SEMANTIC_ROUTING = "semantic_routing"
    OWNER_EVIDENCE = "owner_evidence"
    ANSWER_RENDERING = "answer_rendering"
    AUTHORITY_SAFETY = "authority_safety"
    HANDOFF = "handoff"
    MISSED_T2 = "missed_t2"
    UNNECESSARY_T2 = "unnecessary_t2"
    BUDGET_METERING = "budget_metering"
    LATENCY = "latency"
    EXTERNAL_HOLD = "external_hold"


class HardeningDisposition(StrEnum):
    ELIGIBLE = "eligible"
    HUMAN_REVIEW = "human_review"
    HOLD = "hold"
    NOT_REQUIRED = "not_required"


@dataclass(frozen=True, slots=True)
class HardeningDecision:
    disposition: HardeningDisposition
    weaknesses: tuple[PantheonWeakness, ...]
    reason: str
    automatic_merge: bool = False

    def __post_init__(self) -> None:
        if self.automatic_merge:
            raise ValueError("Pantheon diagnostic hardening MUST NOT merge automatically")


_PROMPT = frozenset(tuple(PantheonRubric)[5:10])
_ROUTING = frozenset(tuple(PantheonRubric)[0:4])
_EVIDENCE = frozenset(tuple(PantheonRubric)[15:20])
_ANSWER = frozenset(tuple(PantheonRubric)[10:15])
_SAFETY = frozenset(tuple(PantheonRubric)[20:25])


def classify_hardening(
    diagnostic: PantheonTurnDiagnostic | None,
    *,
    hold_reason: str | None = None,
) -> HardeningDecision:
    """Permit only bounded non-authority defects to enter isolated hardening."""

    if hold_reason is not None:
        return HardeningDecision(
            disposition=HardeningDisposition.HOLD,
            weaknesses=(PantheonWeakness.EXTERNAL_HOLD,),
            reason=hold_reason,
        )
    if diagnostic is None or diagnostic.verdict is PantheonDiagnosticVerdict.PASS:
        return HardeningDecision(
            disposition=HardeningDisposition.NOT_REQUIRED,
            weaknesses=(),
            reason="diagnostic_passed",
        )
    if (
        diagnostic.verdict is PantheonDiagnosticVerdict.HARD_ZERO_FAIL
        or diagnostic.hard_zero_violations
    ):
        return HardeningDecision(
            disposition=HardeningDisposition.HUMAN_REVIEW,
            weaknesses=(PantheonWeakness.AUTHORITY_SAFETY,),
            reason="hard_zero_requires_human_review",
        )
    failed = {item.rubric for item in diagnostic.results if not item.passed}
    weaknesses: set[PantheonWeakness] = set()
    if failed & _PROMPT:
        weaknesses.add(PantheonWeakness.PROMPT_CONTRACT)
    if failed & _ROUTING:
        weaknesses.add(PantheonWeakness.SEMANTIC_ROUTING)
    if PantheonRubric.HANDOFF_OR_ABSTENTION in failed:
        weaknesses.add(PantheonWeakness.HANDOFF)
    if failed & _EVIDENCE:
        weaknesses.add(PantheonWeakness.OWNER_EVIDENCE)
    if failed & _ANSWER:
        weaknesses.add(PantheonWeakness.ANSWER_RENDERING)
    if failed & _SAFETY:
        weaknesses.add(PantheonWeakness.AUTHORITY_SAFETY)
    if PantheonRubric.REQUIRED_T2_ADMITTED in failed:
        weaknesses.add(PantheonWeakness.MISSED_T2)
    if PantheonRubric.UNNECESSARY_T2_SUPPRESSED in failed:
        weaknesses.add(PantheonWeakness.UNNECESSARY_T2)
    if PantheonRubric.T2_BUDGET_AND_METERING in failed:
        weaknesses.add(PantheonWeakness.BUDGET_METERING)
    if PantheonRubric.T1_PRESERVED in failed:
        weaknesses.add(PantheonWeakness.AUTHORITY_SAFETY)
    if PantheonRubric.LATENCY_AND_TERMINAL_INTEGRITY in failed:
        weaknesses.add(PantheonWeakness.LATENCY)
    human_only = {PantheonWeakness.PROMPT_CONTRACT, PantheonWeakness.AUTHORITY_SAFETY}
    disposition = (
        HardeningDisposition.HUMAN_REVIEW
        if weaknesses & human_only
        else HardeningDisposition.ELIGIBLE
    )
    return HardeningDecision(
        disposition=disposition,
        weaknesses=tuple(sorted(weaknesses, key=str)),
        reason=(
            "prompt_or_authority_change_requires_design_review"
            if disposition is HardeningDisposition.HUMAN_REVIEW
            else "isolated_candidate_allowed"
        ),
    )


__all__ = [
    "HardeningDecision",
    "HardeningDisposition",
    "PantheonWeakness",
    "classify_hardening",
]
