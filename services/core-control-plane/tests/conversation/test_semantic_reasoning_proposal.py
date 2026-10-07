"""Quote resolution for every cue the question-form proposal can carry."""

from __future__ import annotations

from typing import Any

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
