"""Rubric evaluator - pure evaluator + dataclass invariants.

Design reference: ``docs/roadmap/hallucination-rubric-gate.md``.

The rubric is a subtractive hallucination filter. These tests cover the
pure :func:`evaluate_rubric_output` reduction and the
:class:`RubricScore` validation; the gate-integration tests (shadow /
enforce / fail-closed / subtractive-min) live in
:mod:`tests.core.quality_gate.test_rubric_gate`.
"""

from __future__ import annotations

import pytest

from fdai.core.quality_gate.rubric import (
    RubricCriterion,
    RubricOutput,
    RubricScore,
    RubricVerdict,
    evaluate_rubric_output,
)

_KNOWN = ("r.known", "r.other")


def _score(
    *,
    criterion: str = RubricCriterion.FAITHFULNESS.value,
    score: float = 0.9,
    threshold: float = 0.7,
    supporting: tuple[str, ...] = ("r.known",),
) -> RubricScore:
    return RubricScore(
        criterion=criterion,
        score=score,
        threshold=threshold,
        rationale=f"score for {criterion}",
        supporting_rule_ids=supporting,
    )


class TestRubricScoreValidation:
    def test_score_out_of_range_high_rejected(self) -> None:
        with pytest.raises(ValueError, match="score MUST be in"):
            _score(score=1.5)

    def test_score_out_of_range_low_rejected(self) -> None:
        with pytest.raises(ValueError, match="score MUST be in"):
            _score(score=-0.1)

    def test_threshold_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="threshold MUST be in"):
            _score(threshold=1.1)

    def test_empty_criterion_rejected(self) -> None:
        with pytest.raises(ValueError, match="criterion MUST be non-empty"):
            _score(criterion="   ")

    def test_empty_rationale_rejected(self) -> None:
        with pytest.raises(ValueError, match="rationale MUST be non-empty"):
            RubricScore(
                criterion="faithfulness",
                score=0.9,
                threshold=0.7,
                rationale="  ",
            )

    def test_passed_property(self) -> None:
        assert _score(score=0.7, threshold=0.7).passed is True
        assert _score(score=0.69, threshold=0.7).passed is False


class TestEvaluateRubricOutput:
    def test_all_pass(self) -> None:
        out = RubricOutput(
            scores=(
                _score(criterion="faithfulness", score=0.9),
                _score(criterion="completeness", score=0.8),
            )
        )
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.PASS
        assert decision.min_score == pytest.approx(0.8)
        assert decision.failed_criteria == ()

    def test_any_below_threshold_fails(self) -> None:
        out = RubricOutput(
            scores=(
                _score(criterion="faithfulness", score=0.9),
                _score(criterion="completeness", score=0.5, threshold=0.7),
            )
        )
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.FAIL
        assert decision.failed_criteria == ("completeness",)
        assert decision.min_score == pytest.approx(0.5)

    def test_no_scores_abstains(self) -> None:
        decision = evaluate_rubric_output(RubricOutput(), known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert decision.min_score == 0.0
        assert "no_scores" in decision.reasons

    def test_missing_required_criterion_abstains(self) -> None:
        out = RubricOutput(scores=(_score(criterion="faithfulness"),))
        decision = evaluate_rubric_output(
            out,
            known_rule_ids=_KNOWN,
            required_criteria=("faithfulness", "completeness"),
        )
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert any(r.startswith("missing_criterion:completeness") for r in decision.reasons)

    def test_ungrounded_citation_abstains(self) -> None:
        out = RubricOutput(scores=(_score(criterion="faithfulness", supporting=("r.fabricated",)),))
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert any(r.startswith("ungrounded_score:faithfulness") for r in decision.reasons)

    def test_ungrounded_takes_precedence_over_threshold(self) -> None:
        # A below-threshold score that is ALSO ungrounded abstains (the
        # fabricated citation is the stronger signal - we cannot trust the
        # score itself).
        out = RubricOutput(
            scores=(_score(criterion="faithfulness", score=0.2, supporting=("r.fabricated",)),)
        )
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.ABSTAIN

    def test_empty_supporting_ids_still_grounds(self) -> None:
        # A score with no supporting ids is not "ungrounded" - it simply
        # has nothing to validate. Grounding of the citation is the
        # QualityGate's grounding leg's job; the rubric only refuses a
        # citation it can prove is fabricated.
        out = RubricOutput(scores=(_score(supporting=()),))
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.PASS

    def test_off_topic_citation_abstains(self) -> None:
        # Citation id exists but does NOT entail the claim -> abstain.
        out = RubricOutput(scores=(_score(supporting=("r.known",)),))
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN, supports=lambda _rid: False)
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert any(r.startswith("off_topic_score:faithfulness") for r in decision.reasons)

    def test_supports_true_passes(self) -> None:
        out = RubricOutput(scores=(_score(supporting=("r.known",)),))
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN, supports=lambda _rid: True)
        assert decision.verdict is RubricVerdict.PASS

    def test_unknown_id_takes_precedence_over_supports(self) -> None:
        # An id not in the catalog is fabricated - caught before the
        # entailment check even runs.
        out = RubricOutput(scores=(_score(supporting=("r.fabricated",)),))
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN, supports=lambda _rid: True)
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert any(r.startswith("ungrounded_score") for r in decision.reasons)

    def test_min_score_is_minimum_across_criteria(self) -> None:
        out = RubricOutput(
            scores=(
                _score(criterion="faithfulness", score=0.95),
                _score(criterion="completeness", score=0.72),
                _score(criterion="reasoning_coherence", score=0.88),
            )
        )
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.min_score == pytest.approx(0.72)


class TestCatalogSeed:
    def test_shipped_rubric_prompt_loads_and_is_shadow_mode(self) -> None:
        from pathlib import Path

        import yaml

        from fdai.core.prompts.registry import FileSystemPromptRegistry

        repo_root = Path(__file__).resolve().parents[3]
        raw = yaml.safe_load(
            (repo_root / "rule-catalog" / "prompts" / "base" / "t2-rubric.v1.yaml").read_text()
        )
        assert raw["id"] == "t2-rubric"
        assert raw["version"] == 1
        assert raw["layer"] == "rubric"
        assert raw["default_mode"] == "shadow"
        assert raw["applies_to"] == ["t2.rubric.judge"]
        # The prompt narrates the same criteria the pure evaluator enforces.
        for criterion in RubricCriterion:
            assert criterion.value in raw["body"]
        registry = FileSystemPromptRegistry(repo_root / "rule-catalog")
        ids = {a.id for a in registry.artifacts()}
        assert "t2-rubric" in ids

    def test_duplicate_criterion_abstains(self) -> None:
        # A self-contradictory response (same criterion scored twice) is
        # not a signal we trust - abstain regardless of the scores.
        out = RubricOutput(
            scores=(
                _score(criterion="faithfulness", score=0.9),
                _score(criterion="faithfulness", score=0.2),
            )
        )
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert any(r.startswith("duplicate_criterion:faithfulness") for r in decision.reasons)
        assert decision.min_score == 0.0

    def test_unknown_criterion_abstains_when_known_set_supplied(self) -> None:
        out = RubricOutput(scores=(_score(criterion="made_up_dimension", score=0.9),))
        decision = evaluate_rubric_output(
            out,
            known_rule_ids=_KNOWN,
            known_criteria=[c.value for c in RubricCriterion],
        )
        assert decision.verdict is RubricVerdict.ABSTAIN
        assert any(r.startswith("unknown_criterion:made_up_dimension") for r in decision.reasons)

    def test_unknown_criterion_allowed_without_known_set(self) -> None:
        # Backward compatible: no known_criteria -> the check is skipped.
        out = RubricOutput(scores=(_score(criterion="made_up_dimension", score=0.9),))
        decision = evaluate_rubric_output(out, known_rule_ids=_KNOWN)
        assert decision.verdict is RubricVerdict.PASS

    def test_known_criteria_accepts_valid_names(self) -> None:
        out = RubricOutput(
            scores=(
                _score(criterion=RubricCriterion.FAITHFULNESS.value, score=0.9),
                _score(criterion=RubricCriterion.COMPLETENESS.value, score=0.8),
            )
        )
        decision = evaluate_rubric_output(
            out,
            known_rule_ids=_KNOWN,
            known_criteria=[c.value for c in RubricCriterion],
        )
        assert decision.verdict is RubricVerdict.PASS
