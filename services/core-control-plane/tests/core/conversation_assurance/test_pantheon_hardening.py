from __future__ import annotations

from fdai.core.conversation_assurance import (
    HardeningDisposition,
    PantheonDiagnosticVerdict,
    PantheonRubric,
    PantheonRubricResult,
    PantheonTurnDiagnostic,
    PantheonWeakness,
    classify_hardening,
)


def _diagnostic(
    *,
    failed: frozenset[PantheonRubric] = frozenset(),
    hard_zero: tuple[str, ...] = (),
) -> PantheonTurnDiagnostic:
    results = tuple(
        PantheonRubricResult(
            item_id=index,
            rubric=rubric,
            passed=rubric not in failed,
            reason="observed_failure" if rubric in failed else "observed_pass",
        )
        for index, rubric in enumerate(PantheonRubric, start=1)
    )
    score = sum(item.passed for item in results)
    return PantheonTurnDiagnostic(
        case_id="case-1",
        agent="Njord",
        locale="en",
        score=score,
        verdict=(
            PantheonDiagnosticVerdict.HARD_ZERO_FAIL
            if hard_zero
            else PantheonDiagnosticVerdict.FAIL
        ),
        results=results,
        hard_zero_violations=hard_zero,
        trace_receipt_digest="a" * 64,
    )


def test_routing_failure_is_eligible_but_never_auto_merges() -> None:
    decision = classify_hardening(_diagnostic(failed=frozenset({PantheonRubric.PRIMARY_OWNER})))

    assert decision.disposition is HardeningDisposition.ELIGIBLE
    assert decision.weaknesses == (PantheonWeakness.SEMANTIC_ROUTING,)
    assert decision.automatic_merge is False


def test_prompt_and_authority_failures_require_human_review() -> None:
    decision = classify_hardening(
        _diagnostic(
            failed=frozenset(
                {
                    PantheonRubric.AUTHORITY_BOUNDARY,
                    PantheonRubric.SEPARATION_OF_DUTIES,
                }
            )
        )
    )

    assert decision.disposition is HardeningDisposition.HUMAN_REVIEW
    assert PantheonWeakness.PROMPT_CONTRACT in decision.weaknesses
    assert PantheonWeakness.AUTHORITY_SAFETY in decision.weaknesses


def test_hard_zero_stops_automatic_hardening() -> None:
    decision = classify_hardening(_diagnostic(hard_zero=("direct_executor_call",)))

    assert decision.disposition is HardeningDisposition.HUMAN_REVIEW
    assert decision.reason == "hard_zero_requires_human_review"


def test_provider_failure_is_a_hold_not_a_code_defect() -> None:
    decision = classify_hardening(None, hold_reason="provider_unavailable")

    assert decision.disposition is HardeningDisposition.HOLD
    assert decision.weaknesses == (PantheonWeakness.EXTERNAL_HOLD,)


def test_lost_t1_conclusion_requires_human_review() -> None:
    decision = classify_hardening(_diagnostic(failed=frozenset({PantheonRubric.T1_PRESERVED})))

    assert decision.disposition is HardeningDisposition.HUMAN_REVIEW
    assert decision.weaknesses == (PantheonWeakness.AUTHORITY_SAFETY,)
