"""A repair is compared by what it states, never by how the model numbered mentions."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_relabel import relabel_mentions
from fdai.core.conversation.semantic_reasoning_shadow import run_reasoning_shadow
from fdai_service_contracts import semantic_question_form as form_module

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    plan_verifier,
    production_manifest,
)
from tests.conversation.test_semantic_reasoning_shadow import (
    _UTTERANCE,
    _Model,
    _quoted_form,
    _run,
)

_PICKS = {"m2": ["value:compute.vm", "group:compute.vm"]}


def _typed(raw: dict[str, Any], utterance: str = _UTTERANCE) -> SemanticQuestionForm:
    form = resolve_question_form(raw, utterance=utterance).form
    assert form is not None
    return form


def _renumbered() -> dict[str, Any]:
    """The fixture form with its two mentions numbered in the other order."""

    form = _quoted_form()
    form["mentions"] = [
        {**form["mentions"][1], "id": "m1"},
        {**form["mentions"][0], "id": "m2"},
    ]
    goal = form["goals"][0]
    goal["subject"] = "m2"
    goal["filters"] = [{"role": "type", "mention": "m1"}]
    return form


def test_renumbered_mentions_get_back_their_labels_and_every_reference() -> None:
    previous = _typed(_quoted_form())
    restored = relabel_mentions(previous, _typed(_renumbered()))

    # Order is presentation; each label names the same quote and every reference follows.
    assert {item.id: item for item in restored.mentions} == {
        item.id: item for item in previous.mentions
    }
    assert restored.goals == previous.goals
    assert relabel_mentions(previous, previous) is previous


def test_a_new_mention_gets_a_free_label_and_references_follow_the_renaming() -> None:
    previous = _typed(_quoted_form())
    repaired = _renumbered()
    repaired["mentions"].append(
        {
            "id": "m3",
            "form": "name",
            "domain": "instance",
            "span": {"text": "sql-app", "occurrence": 2},
            "qualifier": {"mention": "m2", "sense": "dependency"},
        }
    )
    goal = repaired["goals"][0]
    goal["relation"]["anchor"] = "m2"
    goal["measure"] = {"kind": "count", "group_by": "none", "mention": "m1"}

    restored = relabel_mentions(previous, _typed(repaired))

    quoted = {item.id: _UTTERANCE[item.span.start : item.span.end] for item in restored.mentions}
    assert quoted == {"m1": "sql-app", "m2": "VMs", "m3": "sql-app"}
    (goal_after,) = restored.goals
    assert goal_after.subject == "m1"
    assert [item.mention for item in goal_after.filters] == ["m2"]
    assert goal_after.relation is not None and goal_after.relation.anchor == "m1"
    assert goal_after.measure is not None and goal_after.measure.mention == "m2"
    assert restored.mentions[2].qualifier is not None
    assert restored.mentions[2].qualifier.mention == "m1"


def test_an_ambiguous_or_missing_counterpart_leaves_the_labels_as_written() -> None:
    previous = _typed(_quoted_form())
    doubled = _renumbered()
    doubled["mentions"].append(
        {
            "id": "m3",
            "form": "name",
            "domain": "instance",
            "span": {"text": "sql-app, and what depends on sql-app", "occurrence": 1},
        }
    )
    retyped = _renumbered()
    retyped["mentions"][0]["domain"] = "resource_class"

    for repaired in (doubled, retyped):
        typed = _typed(repaired)
        assert relabel_mentions(previous, typed) is typed


async def test_a_structural_repair_that_renumbers_mentions_is_applied() -> None:
    anchorless = _quoted_form()
    anchorless["goals"][0].update(subject="m2", subject_scope="collection", filters=[])
    model = _Model([anchorless, _renumbered()], _PICKS)

    observation = await _run(model)

    (only_pass,) = observation.passes
    assert only_pass.repair == "applied"
    assert only_pass.disposition == "admitted"
    assert [goal.status for goal in only_pass.goals] == ["compiled"]


_GROUPED = "Count VMs by type please"


def _grouped(**goal: Any) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": {"text": "VMs", "occurrence": 1},
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "count", "group_by": "none"},
                "cue": {"text": "Count", "occurrence": 1},
                "confidence": 0.9,
                **goal,
            }
        ],
        "context": [{"text": "by type please", "occurrence": 1}],
    }


def _extraction(*extra: tuple[str, str]) -> dict[str, Any]:
    items = [("Count", "asks"), ("VMs", "names"), ("by type", "groups"), *extra]
    return {
        "constraints": [
            {"quote": {"text": text, "occurrence": 1}, "role": role} for text, role in items
        ]
    }


async def _shadow(model: _Model, utterance: str) -> Any:
    return await run_reasoning_shadow(
        model=model,
        utterance=utterance,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )


async def test_a_word_a_review_repair_leaves_unplaced_is_judged_by_the_review_again() -> None:
    stated = _grouped(measure={"kind": "count", "group_by": "type", "cue": {"text": "by type"}})
    stated["goals"][0]["measure"]["cue"]["occurrence"] = 1
    stated["context"] = []
    model = _Model([_grouped(), json.loads(json.dumps(stated))], {}, extraction=_extraction())

    observation = await _shadow(model, _GROUPED)

    assert [item.disposition for item in observation.passes] == ["admitted", "admitted"]
    assert observation.passes[1].repair == "review_applied_unaccounted"
    assert observation.review == "faithful" and observation.released is True
    assert len(model.review_calls) == 1


async def test_a_restriction_a_review_repair_leaves_unplaced_is_never_released() -> None:
    utterance = "Count VMs by type running"
    first = _grouped()
    first["context"] = [{"text": "by type running", "occurrence": 1}]
    stated = _grouped(
        measure={"kind": "count", "group_by": "type", "cue": {"text": "by type", "occurrence": 1}}
    )
    stated["context"] = []
    model = _Model([first, stated], {}, extraction=_extraction(("running", "restricts")))

    observation = await _shadow(model, utterance)

    assert observation.passes[1].repair == "review_applied_unaccounted"
    assert observation.review == "unfaithful" and observation.released is False
    assert observation.review_reasons == ("review_uncovered:restricts:18-25",)


def test_a_restored_label_past_the_form_byte_budget_leaves_the_repair_as_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _quoted_form()
    previous["mentions"][1]["id"] = "m10"
    previous["goals"][0]["filters"] = [{"role": "type", "mention": "m10"}]
    typed = _typed(previous)
    repaired = _typed(_quoted_form())
    monkeypatch.setattr(form_module, "MAX_FORM_BYTES", len(repaired.canonical_json().encode()))

    assert relabel_mentions(typed, repaired) is repaired


class _FailingRepairModel(_Model):
    """Propose normally, then fail on the review repair's proposal call."""

    async def propose_form(self, **kwargs: Any) -> dict[str, Any] | None:
        if kwargs.get("repair") is not None:
            raise RuntimeError("provider failed")
        return await super().propose_form(**kwargs)


async def test_a_review_repair_that_fails_is_recorded_and_releases_nothing() -> None:
    model = _FailingRepairModel([_grouped()], {}, extraction=_extraction())

    observation = await _shadow(model, _GROUPED)

    assert [item.disposition for item in observation.passes] == ["admitted", "shadow_error"]
    assert observation.passes[1].reasons == ("shadow_error:RuntimeError",)
    assert observation.released is False
