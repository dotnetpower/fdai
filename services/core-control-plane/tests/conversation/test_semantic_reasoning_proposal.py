"""Quote resolution for every cue the question-form proposal can carry."""

from __future__ import annotations

from typing import Any

from fdai.core.conversation.semantic_reasoning_admission import (
    AdmissionDisposition,
    SpanAccounting,
    admit_question_form,
)
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form

_UTTERANCE = "Which VMs have the highest CPU utilization?"


def _ranked_form(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": {"text": "VMs", "occurrence": 1},
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "metric",
                "span": {"text": "CPU utilization", "occurrence": 1},
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "rank",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "metric", "mention": "m2", "order": order},
                "cue": {"text": "Which", "occurrence": 1},
                "confidence": 0.9,
            }
        ],
    }


def test_a_ranking_order_cue_is_located_like_every_other_cue() -> None:
    resolution = resolve_question_form(
        _ranked_form({"direction": "descending", "cue": {"text": "highest", "occurrence": 1}}),
        utterance=_UTTERANCE,
    )

    assert resolution.form is not None, resolution.failures
    order = resolution.form.goals[0].measure.order  # type: ignore[union-attr]
    assert order is not None and order.cue is not None
    assert _UTTERANCE[order.cue.start : order.cue.end] == "highest"


def test_an_unlocated_order_cue_fails_closed_and_a_missing_one_stays_optional() -> None:
    unlocated = resolve_question_form(
        _ranked_form({"direction": "descending", "cue": {"text": "largest", "occurrence": 1}}),
        utterance=_UTTERANCE,
    )
    without = resolve_question_form(_ranked_form({"direction": "descending"}), utterance=_UTTERANCE)

    assert unlocated.form is None
    assert any("goals.0.measure.order.cue" in note for note in unlocated.notes)
    assert without.form is not None, without.failures


_THRESHOLD = "Which VMs have CPU utilization above 90%?"


def _threshold_form(*, value: str = "90", unit: dict[str, Any] | None = None) -> dict[str, Any]:
    comparison: dict[str, Any] = {
        "comparator": "gt",
        "value": value,
        "value_span": {"text": "90", "occurrence": 1},
        "comparator_span": {"text": "above", "occurrence": 1},
        "unit": "percent",
        "unit_span": {"text": "%", "occurrence": 1},
    }
    if unit is not None:
        comparison.update(unit)
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": {"text": "VMs", "occurrence": 1},
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "metric",
                "span": {"text": "CPU utilization", "occurrence": 1},
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "metric", "mention": "m2", "comparison": comparison}],
                "cue": {"text": "Which", "occurrence": 1},
                "confidence": 0.9,
            }
        ],
    }


def _admit(form: dict[str, Any], utterance: str) -> Any:
    resolution = resolve_question_form(form, utterance=utterance)
    assert resolution.form is not None, resolution.failures
    # Word accounting is checked elsewhere; these tests isolate the comparison checks.
    return admit_question_form(
        resolution.form, utterance=utterance, accounting=SpanAccounting(required=False)
    )


def test_a_metric_threshold_resolves_and_admits_with_its_copied_value() -> None:
    admission = _admit(_threshold_form(), _THRESHOLD)

    assert admission.disposition is AdmissionDisposition.ADMITTED, admission.reasons
    comparison = admission.form.goals[0].filters[0].comparison
    assert comparison is not None and comparison.value == "90"
    assert _THRESHOLD[comparison.value_span.start : comparison.value_span.end] == "90"


def test_a_threshold_that_differs_from_its_quoted_digits_never_admits() -> None:
    admission = _admit(_threshold_form(value="95"), _THRESHOLD)

    assert admission.disposition is AdmissionDisposition.INVALID
    assert admission.reasons == ("comparison_value_mismatch:g1",)


def test_a_threshold_without_its_unit_clarifies_and_never_inherits_one() -> None:
    utterance = "Which VMs have CPU utilization above 90?"
    form = _threshold_form(unit={"unit": "unit_unstated", "unit_span": None})
    admission = _admit(form, utterance)

    assert admission.disposition is AdmissionDisposition.CLARIFY
    assert admission.reasons == ("metric_unit_unstated:g1",)


def test_a_metric_filter_without_a_threshold_asks_for_one() -> None:
    utterance = "Which VMs have high CPU utilization?"
    form = _threshold_form()
    del form["goals"][0]["filters"][0]["comparison"]

    admission = _admit(form, utterance)

    assert admission.disposition is AdmissionDisposition.CLARIFY
    assert admission.reasons == ("metric_threshold_unstated:g1",)


def test_a_stated_limit_needs_its_span() -> None:
    unstated_limit = _ranked_form({"direction": "descending", "limit": 3})

    assert resolve_question_form(unstated_limit, utterance=_UTTERANCE).form is None


def test_a_rank_without_the_words_that_order_it_never_admits() -> None:
    admission = _admit(_ranked_form({"direction": "descending"}), _UTTERANCE)

    assert admission.disposition is AdmissionDisposition.INVALID
    assert admission.reasons == ("order_cue_required:g1",)
