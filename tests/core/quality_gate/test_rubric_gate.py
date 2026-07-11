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
    quality_decision_audit_fields,
)
from fdai.core.quality_gate.critic import CriticOutput, CriticStance
from fdai.core.quality_gate.debate import DebateOrchestrator
from fdai.core.quality_gate.debate_router import DebateRouterConfig
from fdai.core.quality_gate.judge import JudgeDecision, JudgeOutput
from fdai.core.quality_gate.rubric import RubricCriterion, RubricOutput, RubricScore
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    MismatchCrossCheckModel,
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


def _candidate(*, confidence: float = 0.9, reasoning_trace: str | None = None) -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("r.known",),
        confidence_signals={"retrieval": confidence, "verifier_margin": confidence},
        reasoning_trace=(
            "The bucket is missing the owner tag; rule r.known requires it."
            if reasoning_trace is None
            else reasoning_trace
        ),
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


@pytest.mark.asyncio
async def test_enforce_abstains_on_empty_reasoning_trace() -> None:
    # A blank reasoning_trace cannot be scored for faithfulness; enforce
    # mode abstains WITHOUT spending a judge call, folding confidence to 0.
    ev = UniformRubricEvaluator(
        criteria=_CRITERIA, score=1.0, threshold=0.7, supporting_rule_ids=("r.known",)
    )
    gate = _gate(rubric_evaluator=ev, rubric_shadow=False)
    decision = await gate.evaluate(_candidate(reasoning_trace="   "))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.rubric_verdict == "abstain"
    assert any(r.startswith("rubric_no_reasoning_trace") for r in decision.reasons)
    assert decision.rubric_scores == ()
    assert decision.aggregate_confidence == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_shadow_empty_reasoning_trace_does_not_block() -> None:
    ev = UniformRubricEvaluator(
        criteria=_CRITERIA, score=1.0, threshold=0.7, supporting_rule_ids=("r.known",)
    )
    gate = _gate(rubric_evaluator=ev, rubric_shadow=True)
    decision = await gate.evaluate(_candidate(reasoning_trace=""))
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.rubric_shadow is True
    assert decision.rubric_verdict == "abstain"
    assert decision.aggregate_confidence == pytest.approx(0.9)


class _EntailmentGrounding(InMemoryGroundingSource):
    """Grounding source with an entailment predicate for the rubric leg."""

    def __init__(self, rules: dict[str, Rule], *, entails: bool) -> None:
        super().__init__(rules)
        self._entails = entails

    def supports(self, candidate: QualityCandidate, rule_id: str) -> bool:
        del candidate, rule_id
        return self._entails


@pytest.mark.asyncio
async def test_enforce_off_topic_citation_abstains() -> None:
    # Grounding source reports the citation does NOT entail the candidate.
    # Both the grounding leg and the rubric entailment check fire; the
    # rubric verdict is abstain and the outcome routes to HIL.
    ev = UniformRubricEvaluator(
        criteria=_CRITERIA, score=0.95, threshold=0.7, supporting_rule_ids=("r.known",)
    )
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=_EntailmentGrounding({"r.known": _rule("r.known")}, entails=False),
        config=QualityGateConfig(
            confidence_threshold=0.5,
            require_grounding=True,
            require_cross_check_quorum=2,
            rubric_shadow=False,
            rubric_required_criteria=_CRITERIA,
        ),
        rubric_evaluator=ev,
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.rubric_verdict == "abstain"
    assert any(r.startswith("rubric_abstained") for r in decision.reasons)


class _RaisingGrounding(InMemoryGroundingSource):
    """Grounding source whose entailment check raises (backend down)."""

    def supports(self, candidate: QualityCandidate, rule_id: str) -> bool:
        del candidate, rule_id
        raise RuntimeError("embedding backend down")


@pytest.mark.asyncio
async def test_grounding_supports_error_fails_closed() -> None:
    # A grounding backend failure MUST fail closed to HIL, never crash the
    # gate - on both the grounding leg AND the rubric entailment leg.
    ev = UniformRubricEvaluator(
        criteria=_CRITERIA, score=0.95, threshold=0.7, supporting_rule_ids=("r.known",)
    )
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=_RaisingGrounding({"r.known": _rule("r.known")}),
        config=QualityGateConfig(
            confidence_threshold=0.5,
            require_grounding=True,
            require_cross_check_quorum=2,
            rubric_shadow=False,
            rubric_required_criteria=_CRITERIA,
        ),
        rubric_evaluator=ev,
    )
    # MUST NOT raise.
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ABSTAIN
    # Grounding leg treated the citation as ungrounded (fail-closed)...
    assert any(r.startswith("ungrounded_citation") for r in decision.reasons)
    # ...and the rubric leg fell into its own fail-closed abstain.
    assert any(r.startswith("rubric_evaluator_error") for r in decision.reasons)


@pytest.mark.asyncio
async def test_audit_fields_include_rubric_provenance() -> None:
    # The audit helper MUST surface the rubric_* provenance so shadow-mode
    # catch / false-positive metrics can be computed from the audit log.
    import json

    gate = _gate(rubric_evaluator=_failing_rubric(), rubric_shadow=True)
    decision = await gate.evaluate(_candidate())
    fields = quality_decision_audit_fields(decision)
    assert fields["rubric_verdict"] == "fail"
    assert fields["rubric_shadow"] is True
    assert fields["rubric_min_score"] == pytest.approx(0.2)
    assert {s["criterion"] for s in fields["rubric_scores"]} == set(_CRITERIA)
    # Audit essence: which action / resource the decision was about.
    assert fields["candidate_action_type"] == "remediate.tag-add"
    assert fields["candidate_target_resource_ref"] == "rid-1"
    # Security: rationale (untrusted LLM free-text) is EXCLUDED by default.
    assert all("rationale" not in s for s in fields["rubric_scores"])
    # JSON-safe: no enums / dataclasses leak through.
    json.dumps(fields)


@pytest.mark.asyncio
async def test_audit_rationale_is_opt_in_and_capped() -> None:
    gate = _gate(rubric_evaluator=_failing_rubric(), rubric_shadow=True)
    decision = await gate.evaluate(_candidate())
    fields = quality_decision_audit_fields(decision, include_rationale=True)
    # Opt-in: rationale present now, and every score has one.
    assert all(s["rationale"] for s in fields["rubric_scores"])
    # Capped to bound the untrusted free-text surface.
    assert all(len(s["rationale"]) <= 500 for s in fields["rubric_scores"])


# ---------------------------------------------------------------------------
# Regression: debate resolving a cross-check disagreement MUST NOT let a
# rubric FAIL leak through to ELIGIBLE. The rubric is subtractive on every
# path, including the debate-resolved one.
# ---------------------------------------------------------------------------


class _AgreeCritic:
    async def critique(self, candidate: object, proposer_output: object) -> CriticOutput:
        del candidate, proposer_output
        return CriticOutput(stance=CriticStance.AGREE, objections=(), citations=())


class _AcceptJudge:
    async def judge(
        self, candidate: object, proposer_output: object, critic_output: object
    ) -> JudgeOutput:
        del candidate, proposer_output, critic_output
        return JudgeOutput(decision=JudgeDecision.ACCEPT, justification="ok")


def _partial_fail_rubric() -> StaticRubricEvaluator:
    # min_score = 0.6 (a FAIL on faithfulness) but ABOVE a 0.5 confidence
    # threshold, so the confidence leg does NOT add a reason - the ONLY
    # thing that can route this to HIL is the rubric_failed reason itself.
    return StaticRubricEvaluator(
        output=RubricOutput(
            scores=(
                RubricScore(
                    criterion=RubricCriterion.FAITHFULNESS.value,
                    score=0.6,
                    threshold=0.7,
                    rationale="one unsupported claim",
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
async def test_debate_resolved_disagreement_still_honors_rubric_fail() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        # agree=1 < quorum=2 -> cross_check_below_quorum -> debate route.
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MismatchCrossCheckModel(model_id="m2"),
        ),
        grounding=InMemoryGroundingSource({"r.known": _rule("r.known")}),
        config=QualityGateConfig(
            confidence_threshold=0.5,
            require_grounding=True,
            require_cross_check_quorum=2,
            rubric_shadow=False,
            rubric_required_criteria=_CRITERIA,
        ),
        debate_orchestrator=DebateOrchestrator(critic=_AgreeCritic(), judge=_AcceptJudge()),
        debate_router_config=DebateRouterConfig(),
        rubric_evaluator=_partial_fail_rubric(),
    )
    decision = await gate.evaluate(_candidate(confidence=0.9))
    # The debate PROCEEDs (resolves the cross-check disagreement), but the
    # rubric FAILed - the outcome MUST be ABSTAIN, not ELIGIBLE.
    assert decision.rubric_verdict == "fail"
    assert any(r.startswith("rubric_failed") for r in decision.reasons)
    assert decision.outcome is QualityOutcome.ABSTAIN
    # Confidence was folded down to the min rubric score (subtractive).
    assert decision.aggregate_confidence == pytest.approx(0.6)
