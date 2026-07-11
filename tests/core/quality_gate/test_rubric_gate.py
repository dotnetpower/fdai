"""QualityGate x rubric - shadow / enforce / subtractive / fail-closed.

Design reference: ``docs/roadmap/hallucination-rubric-gate.md``.

Proves the core invariants:

- **Shadow (default)**: a rubric FAIL is recorded but does NOT change
  the outcome or confidence (judge-and-log).
- **Enforce**: a rubric FAIL routes to HIL (abstain); a below-threshold
  min score lowers confidence.
- **Subtractive**: the rubric can only *lower* the aggregate confidence
  (``min()``), never raise it - a good candidate the rubric passes stays
  eligible, and the rubric can never flip a would-be-abstain into
  eligible.
- **Fail-closed**: an evaluator exception aborts to HIL, never to
  eligible.
"""

from __future__ import annotations

import pytest

from fdai.core.quality_gate import (
    QualityCandidate,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
)
from fdai.core.quality_gate.rubric import RubricCriterion, RubricOutput, RubricScore
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    StaticRubricEvaluator,
    StaticVerifier,
    UniformRubricEvaluator,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)

_CRITERIA = (
    RubricCriterion.FAITHFULNESS.value,
    RubricCriterion.EVIDENCE_ACTION_ALIGNMENT.value,
)


def _rule(rule_id: str) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _candidate(*, confidence: float = 0.9) -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("r.known",),
        confidence_signals={"retrieval": confidence, "verifier_margin": confidence},
        reasoning_trace="The bucket is missing the owner tag; rule r.known requires it.",
    )


def _gate(
    *,
    rubric_evaluator: object,
    rubric_shadow: bool,
    confidence_threshold: float = 0.7,
) -> QualityGate:
    return QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=InMemoryGroundingSource({"r.known": _rule("r.known")}),
        config=QualityGateConfig(
            confidence_threshold=confidence_threshold,
            require_grounding=True,
            require_cross_check_quorum=2,
            rubric_shadow=rubric_shadow,
            rubric_required_criteria=_CRITERIA,
        ),
        rubric_evaluator=rubric_evaluator,  # type: ignore[arg-type]
    )


def _failing_rubric() -> StaticRubricEvaluator:
    return StaticRubricEvaluator(
        output=RubricOutput(
            scores=(
                RubricScore(
                    criterion=RubricCriterion.FAITHFULNESS.value,
                    score=0.2,
                    threshold=0.7,
                    rationale="unsupported claim",
                    supporting_rule_ids=("r.known",),
                ),
                RubricScore(
                    criterion=RubricCriterion.EVIDENCE_ACTION_ALIGNMENT.value,
                    score=0.9,
                    threshold=0.7,
                    rationale="aligned",
                    supporting_rule_ids=("r.known",),
                ),
            )
        )
    )


@pytest.mark.asyncio
async def test_shadow_records_but_does_not_block() -> None:
    gate = _gate(rubric_evaluator=_failing_rubric(), rubric_shadow=True)
    decision = await gate.evaluate(_candidate())
    # Shadow: outcome stays eligible even though the rubric failed.
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.rubric_shadow is True
    assert decision.rubric_verdict == "fail"
    assert decision.rubric_min_score == pytest.approx(0.2)
    # No rubric reason leaked into the outcome-driving reasons.
    assert not any(r.startswith("rubric_failed") for r in decision.reasons)
    # Confidence NOT lowered in shadow.
    assert decision.aggregate_confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_enforce_fail_routes_to_hil() -> None:
    gate = _gate(rubric_evaluator=_failing_rubric(), rubric_shadow=False)
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.rubric_shadow is False
    assert decision.rubric_verdict == "fail"
    assert any(r.startswith("rubric_failed:faithfulness") for r in decision.reasons)
    # Subtractive: confidence lowered to the min rubric score.
    assert decision.aggregate_confidence == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_enforce_pass_stays_eligible() -> None:
    ev = UniformRubricEvaluator(
        criteria=_CRITERIA, score=0.95, threshold=0.7, supporting_rule_ids=("r.known",)
    )
    gate = _gate(rubric_evaluator=ev, rubric_shadow=False)
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.rubric_verdict == "pass"
    # min(0.9 candidate, 0.95 rubric) = 0.9 - rubric did NOT raise it.
    assert decision.aggregate_confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_rubric_is_subtractive_never_additive() -> None:
    # Candidate confidence is LOW (below threshold); a high rubric score
    # MUST NOT rescue it - the rubric can only lower, never raise.
    ev = UniformRubricEvaluator(
        criteria=_CRITERIA, score=1.0, threshold=0.7, supporting_rule_ids=("r.known",)
    )
    gate = _gate(rubric_evaluator=ev, rubric_shadow=False, confidence_threshold=0.7)
    decision = await gate.evaluate(_candidate(confidence=0.3))
    assert decision.aggregate_confidence == pytest.approx(0.3)
    assert decision.outcome is QualityOutcome.ABSTAIN


@pytest.mark.asyncio
async def test_enforce_abstain_on_missing_criterion() -> None:
    # Evaluator returns only one of the two required criteria.
    ev = StaticRubricEvaluator(
        output=RubricOutput(
            scores=(
                RubricScore(
                    criterion=RubricCriterion.FAITHFULNESS.value,
                    score=0.9,
                    threshold=0.7,
                    rationale="ok",
                    supporting_rule_ids=("r.known",),
                ),
            )
        )
    )
    gate = _gate(rubric_evaluator=ev, rubric_shadow=False)
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.rubric_verdict == "abstain"
    assert any(r.startswith("rubric_abstained") for r in decision.reasons)


@pytest.mark.asyncio
async def test_fail_closed_on_evaluator_error() -> None:
    ev = StaticRubricEvaluator(raises=RuntimeError("model transport failed"))
    gate = _gate(rubric_evaluator=ev, rubric_shadow=False)
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.rubric_verdict == "abstain"
    assert any(r.startswith("rubric_evaluator_error:RuntimeError") for r in decision.reasons)
    # Fail-closed: min score driven to 0.0.
    assert decision.aggregate_confidence == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_shadow_fail_closed_error_does_not_block() -> None:
    # An evaluator error in shadow mode is recorded but MUST NOT change
    # the outcome (shadow never blocks).
    ev = StaticRubricEvaluator(raises=RuntimeError("boom"))
    gate = _gate(rubric_evaluator=ev, rubric_shadow=True)
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.rubric_shadow is True
    assert decision.aggregate_confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_no_rubric_wired_is_unchanged() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=InMemoryGroundingSource({"r.known": _rule("r.known")}),
        config=QualityGateConfig(confidence_threshold=0.7, require_cross_check_quorum=2),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.rubric_scores == ()
    assert decision.rubric_verdict is None
    assert decision.rubric_shadow is False
