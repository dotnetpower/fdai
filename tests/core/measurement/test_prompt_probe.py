"""Unit tests for :mod:`aiopspilot.core.measurement.prompt_probe`.

Every case exercises the pure evaluator functions with hand-crafted
inputs so a regression narrows immediately to the offending helper.
"""

from __future__ import annotations

import pytest

from aiopspilot.core.measurement.prompt_probe import (
    CitationScores,
    ExpectedResponse,
    RequiredField,
    evaluate_adherence,
    evaluate_canary_echoes,
    evaluate_citations,
    score_recognition,
)

# ---------------------------------------------------------------------------
# evaluate_adherence
# ---------------------------------------------------------------------------


class TestEvaluateAdherence:
    def test_non_json_returns_single_violation(self) -> None:
        passed, violations = evaluate_adherence(None, (RequiredField("x", "string"),))
        assert not passed
        # Fail-closed: one structured code, not a fan-out of missing-field errors.
        assert violations == ("not-a-json-object",)

    def test_all_fields_present_and_typed_passes(self) -> None:
        response = {"action_type": "noop", "params": {"k": "v"}}
        passed, violations = evaluate_adherence(
            response,
            (
                RequiredField("action_type", "string"),
                RequiredField("params", "object", non_empty=False),
            ),
        )
        assert passed
        assert violations == ()

    def test_missing_field_surfaces_structured_code(self) -> None:
        passed, violations = evaluate_adherence(
            {"params": {}},
            (RequiredField("action_type", "string"),),
        )
        assert not passed
        assert violations == ("missing-field:action_type",)

    def test_wrong_type_surfaces_structured_code(self) -> None:
        passed, violations = evaluate_adherence(
            {"action_type": ["not-a-string"]},
            (RequiredField("action_type", "string"),),
        )
        assert not passed
        assert violations == ("wrong-type:action_type",)

    def test_empty_string_fails_when_non_empty_required(self) -> None:
        passed, violations = evaluate_adherence(
            {"action_type": ""},
            (RequiredField("action_type", "string"),),
        )
        assert not passed
        assert violations == ("empty-field:action_type",)

    def test_empty_object_allowed_when_non_empty_false(self) -> None:
        passed, violations = evaluate_adherence(
            {"params": {}},
            (RequiredField("params", "object", non_empty=False),),
        )
        assert passed
        assert violations == ()

    def test_multiple_violations_are_all_reported(self) -> None:
        passed, violations = evaluate_adherence(
            {"action_type": 123, "params": None},
            (
                RequiredField("action_type", "string"),
                RequiredField("params", "object"),
            ),
        )
        assert not passed
        # Both fields fail - once each, distinct codes.
        assert "wrong-type:action_type" in violations
        assert "wrong-type:params" in violations
        assert len(violations) == 2

    def test_array_type_accepts_list_and_tuple(self) -> None:
        passed_list, _ = evaluate_adherence(
            {"ids": [1, 2]}, (RequiredField("ids", "array", non_empty=False),)
        )
        passed_tuple, _ = evaluate_adherence(
            {"ids": (1, 2)}, (RequiredField("ids", "array", non_empty=False),)
        )
        assert passed_list is True
        assert passed_tuple is True

    def test_unknown_expected_type_raises_at_check_time(self) -> None:
        with pytest.raises(ValueError, match="expected_type"):
            evaluate_adherence({"x": 1}, (RequiredField("x", "integer"),))


# ---------------------------------------------------------------------------
# evaluate_canary_echoes
# ---------------------------------------------------------------------------


class TestEvaluateCanaryEchoes:
    def test_empty_canary_mapping_yields_empty_result(self) -> None:
        assert evaluate_canary_echoes("hi", None) == {}
        assert evaluate_canary_echoes("hi", {}) == {}

    def test_present_and_absent_tokens_are_reported(self) -> None:
        canaries = {"head": "CN_HEAD_9x9", "tail": "CN_TAIL_1y1"}
        response = "the model said CN_HEAD_9x9 but not the tail marker"
        got = evaluate_canary_echoes(response, canaries)
        assert got == {"head": True, "tail": False}

    def test_case_sensitivity_is_preserved(self) -> None:
        """Canaries are random opaque tokens - a case-insensitive match
        would let a model that reformatted output to lowercase pass a
        probe it should have failed."""

        got = evaluate_canary_echoes(
            "the response contains cn_head_9x9 in lower case",
            {"head": "CN_HEAD_9x9"},
        )
        assert got == {"head": False}


# ---------------------------------------------------------------------------
# evaluate_citations
# ---------------------------------------------------------------------------


class TestEvaluateCitations:
    def test_empty_expected_returns_none(self) -> None:
        assert evaluate_citations(["a", "b"], []) is None

    def test_perfect_match_scores_one(self) -> None:
        scores = evaluate_citations(["rule.a", "rule.b"], ["rule.a", "rule.b"])
        assert scores == CitationScores(precision=1.0, recall=1.0, f1=1.0)

    def test_missing_returned_ids_scores_zero(self) -> None:
        scores = evaluate_citations([], ["rule.a", "rule.b"])
        assert scores is not None
        assert scores.precision == 0.0
        assert scores.recall == 0.0
        assert scores.f1 == 0.0

    def test_hallucinated_id_lowers_precision(self) -> None:
        scores = evaluate_citations(["rule.a", "rule.hallucinated"], ["rule.a"])
        assert scores is not None
        assert scores.precision == pytest.approx(0.5)
        assert scores.recall == pytest.approx(1.0)
        assert scores.f1 == pytest.approx(2 / 3)

    def test_missed_id_lowers_recall(self) -> None:
        scores = evaluate_citations(["rule.a"], ["rule.a", "rule.b"])
        assert scores is not None
        assert scores.precision == pytest.approx(1.0)
        assert scores.recall == pytest.approx(0.5)
        assert scores.f1 == pytest.approx(2 / 3)

    def test_duplicates_do_not_affect_score(self) -> None:
        scores = evaluate_citations(["rule.a", "rule.a", "rule.a"], ["rule.a", "rule.a"])
        assert scores == CitationScores(precision=1.0, recall=1.0, f1=1.0)

    def test_empty_string_ids_are_ignored(self) -> None:
        scores = evaluate_citations(["", "rule.a"], ["rule.a", ""])
        assert scores == CitationScores(precision=1.0, recall=1.0, f1=1.0)


# ---------------------------------------------------------------------------
# score_recognition aggregate
# ---------------------------------------------------------------------------


class TestScoreRecognition:
    def _expected(self, **overrides: object) -> ExpectedResponse:
        base: dict[str, object] = {
            "required_fields": (
                RequiredField("action_type", "string"),
                RequiredField("params", "object", non_empty=False),
            ),
            "expected_cited_rule_ids": (),
            "canary_tokens": None,
        }
        base.update(overrides)
        return ExpectedResponse(**base)  # type: ignore[arg-type]

    def test_full_pass(self) -> None:
        expected = self._expected(
            expected_cited_rule_ids=("rule.a",),
            canary_tokens={"head": "CANARY_TOKEN_XYZ"},
        )
        result = score_recognition(
            expected=expected,
            response_json={
                "action_type": "noop",
                "params": {},
                "cited_rule_ids": ["rule.a"],
            },
            response_text=(
                '{"action_type": "noop", "params": {}, "cited_rule_ids": '
                '["rule.a"], "note": "CANARY_TOKEN_XYZ"}'
            ),
        )
        assert result.adherence_pass is True
        assert result.adherence_violations == ()
        assert result.canary_echoes == {"head": True}
        assert result.citations == CitationScores(precision=1.0, recall=1.0, f1=1.0)

    def test_non_json_response_fails_adherence_but_still_scores_canary(self) -> None:
        expected = self._expected(canary_tokens={"head": "CANARY_TOKEN_XYZ"})
        result = score_recognition(
            expected=expected,
            response_json=None,
            response_text="raw text with CANARY_TOKEN_XYZ inside",
        )
        assert result.adherence_pass is False
        assert result.adherence_violations == ("not-a-json-object",)
        # Canary probe still runs against the raw text.
        assert result.canary_echoes == {"head": True}
        # Citation probe returns None when no expected ids were supplied.
        assert result.citations is None

    def test_citation_reads_tolerate_missing_field(self) -> None:
        """A response with the required top-level fields but no
        ``cited_rule_ids`` MUST score zero recall on citations, not
        raise."""

        expected = self._expected(expected_cited_rule_ids=("rule.a",))
        result = score_recognition(
            expected=expected,
            response_json={"action_type": "noop", "params": {}},
            response_text="",
        )
        assert result.adherence_pass is True
        assert result.citations is not None
        assert result.citations.recall == 0.0
        assert result.citations.precision == 0.0

    def test_citation_extraction_ignores_wrong_types(self) -> None:
        """A model that returns ``cited_rule_ids: "rule.a"`` (a string
        instead of a list) MUST NOT crash the extractor."""

        expected = self._expected(expected_cited_rule_ids=("rule.a",))
        result = score_recognition(
            expected=expected,
            response_json={
                "action_type": "noop",
                "params": {},
                "cited_rule_ids": "rule.a",  # wrong type on purpose
            },
            response_text="",
        )
        assert result.citations is not None
        assert result.citations.recall == 0.0


# ---------------------------------------------------------------------------
# summarize_recognition aggregate (Wave 3 step D-2b-i)
# ---------------------------------------------------------------------------


class TestSummarizeRecognition:
    """Aggregation contract tests.

    The aggregate feeds every downstream consumer (dashboard rows,
    scenario runner, promotion gate) so its edge cases matter more
    than its happy path.
    """

    def _result(
        self,
        *,
        adherence_pass: bool = True,
        violations: tuple[str, ...] = (),
        canary_echoes: dict[str, bool] | None = None,
        citations: CitationScores | None = None,
    ):
        from aiopspilot.core.measurement.prompt_probe import RecognitionResult

        return RecognitionResult(
            adherence_pass=adherence_pass,
            adherence_violations=violations,
            canary_echoes=canary_echoes or {},
            citations=citations,
        )

    def test_empty_batch_returns_neutral_summary(self) -> None:
        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition([])
        assert summary.sample_count == 0
        assert summary.adherence_pass_rate == 0.0
        assert summary.adherence_violation_counts == {}
        assert summary.per_layer_canary_echo_rate == {}
        # ``None`` rather than 0.0 so a downstream emitter can skip
        # publishing a citation row instead of reporting a misleading
        # zero average.
        assert summary.mean_citation_f1 is None

    def test_all_pass_reports_one(self) -> None:
        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition([self._result(), self._result(), self._result()])
        assert summary.sample_count == 3
        assert summary.adherence_pass_rate == 1.0
        assert summary.adherence_violation_counts == {}

    def test_adherence_rate_is_fractional(self) -> None:
        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition(
            [
                self._result(adherence_pass=True),
                self._result(adherence_pass=False, violations=("not-a-json-object",)),
            ]
        )
        assert summary.adherence_pass_rate == pytest.approx(0.5)

    def test_violation_codes_are_counted_across_samples(self) -> None:
        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition(
            [
                self._result(
                    adherence_pass=False,
                    violations=("missing-field:action_type",),
                ),
                self._result(
                    adherence_pass=False,
                    violations=(
                        "missing-field:action_type",
                        "wrong-type:params",
                    ),
                ),
            ]
        )
        assert summary.adherence_violation_counts == {
            "missing-field:action_type": 2,
            "wrong-type:params": 1,
        }

    def test_per_layer_echo_rate_uses_measured_denominator(self) -> None:
        """A layer that was measured in one sample but not another
        MUST use its actual denominator, not the batch size, so a
        layer that only appeared in tool-manifest-enabled samples is
        scored against the runs that could have echoed it."""

        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition(
            [
                self._result(canary_echoes={"base": True, "tool-manifest": True}),
                self._result(canary_echoes={"base": False}),  # no tool-manifest layer
                self._result(canary_echoes={"base": True, "tool-manifest": False}),
            ]
        )
        # base appeared in all 3; 2 echoes -> 2/3.
        assert summary.per_layer_canary_echo_rate["base"] == pytest.approx(2 / 3)
        # tool-manifest appeared in only 2 samples; 1 echoed -> 1/2.
        assert summary.per_layer_canary_echo_rate["tool-manifest"] == pytest.approx(0.5)

    def test_layers_never_measured_do_not_appear(self) -> None:
        """A sample without any canary echoes MUST NOT force a
        zero-denominator entry into the rate map."""

        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition(
            [
                self._result(canary_echoes={}),  # measurement disabled for this sample
                self._result(canary_echoes={"base": True}),
            ]
        )
        assert set(summary.per_layer_canary_echo_rate.keys()) == {"base"}
        assert summary.per_layer_canary_echo_rate["base"] == pytest.approx(1.0)

    def test_citation_mean_excludes_none_scored_samples(self) -> None:
        """Samples where the caller passed no expected ids MUST NOT
        dilute the F1 average; only scored samples count."""

        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition(
            [
                self._result(citations=CitationScores(1.0, 1.0, 1.0)),
                self._result(citations=None),  # not scored
                self._result(citations=CitationScores(0.5, 0.5, 0.5)),
            ]
        )
        # Mean of only the two scored samples = 0.75, not (1.0 + 0.5) / 3.
        assert summary.mean_citation_f1 == pytest.approx(0.75)

    def test_citation_mean_is_none_when_no_sample_scored(self) -> None:
        from aiopspilot.core.measurement.prompt_probe import summarize_recognition

        summary = summarize_recognition(
            [
                self._result(citations=None),
                self._result(citations=None),
            ]
        )
        assert summary.mean_citation_f1 is None
