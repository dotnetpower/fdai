"""A kind the proposer placed in the wrong catalog is grounded in the sibling catalog."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation import semantic_reasoning_form as form_module
from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_kinds import eligible_kind_mentions
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_shadow import ShadowBudget, run_reasoning_shadow

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    plan_verifier,
    production_manifest,
)
from tests.conversation.test_semantic_reasoning_shadow import _Model

_INCIDENTS = "List the open incidents"
_GROUPS = "List the resource groups"


def _quote(text: str, occurrence: int = 1) -> dict[str, Any]:
    return {"text": text, "occurrence": occurrence}


def _goal(**extra: Any) -> dict[str, Any]:
    goal: dict[str, Any] = {
        "id": "g1",
        "level": "instance",
        "operation": "select",
        "subject": "m1",
        "subject_scope": "collection",
        "cue": _quote("List"),
        "confidence": 0.9,
    }
    goal.update(extra)
    return goal


def _incidents(domain: str = "resource_type") -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": domain, "span": _quote("incidents")},
            {"id": "m2", "form": "value", "domain": "state", "span": _quote("open")},
        ],
        "goals": [_goal(filters=[{"role": "state", "mention": "m2"}])],
        "context": [_quote("the")],
    }


def _groups(domain: str = "object_type") -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": domain, "span": _quote("resource groups")}
        ],
        "goals": [_goal()],
        "context": [_quote("the")],
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
        retain_compilations=True,
    )


class _RunoffModel(_Model):
    """Answer a shard that mixes both kind catalogs with fixed picks per chooser."""

    def __init__(self, *args: Any, runoff: tuple[str, str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.runoff = runoff
        self.runoff_calls = 0

    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
        second: bool = False,
    ) -> dict[str, Any]:
        kinds = {candidate.id.startswith("object:") for candidate in shard.candidates}
        if kinds != {True, False}:
            return await super().choose_concepts(
                utterance=utterance, mentions=mentions, shard=shard, second=second
            )
        self.runoff_calls += 1
        pick = self.runoff[1 if second else 0]
        return {
            "shard_digest": shard.digest,
            "choices": [{"mention": item["mention"], "candidate_ids": [pick]} for item in mentions],
        }


def _typed(raw: dict[str, Any], utterance: str) -> SemanticQuestionForm:
    form = resolve_question_form(raw, utterance=utterance).form
    assert form is not None
    return form


def test_only_an_instance_collection_subject_may_change_its_kind() -> None:
    counted = _groups()
    counted["goals"] = [
        _goal(operation="count", measure={"kind": "count", "group_by": "none", "mention": "m1"})
    ]
    filtered = _groups()
    filtered["mentions"].append(
        {"id": "m2", "form": "concept", "domain": "resource_type", "span": _quote("groups")}
    )
    filtered["mentions"][0]["span"] = _quote("resource")
    filtered["goals"] = [_goal(filters=[{"role": "type", "mention": "m2"}])]
    schema = _groups()
    schema["goals"] = [_goal(level="schema")]

    assert eligible_kind_mentions(_typed(_groups(), _GROUPS)) == {"m1"}
    assert eligible_kind_mentions(_typed(counted, _GROUPS)) == {"m1"}
    # A type filter reads only a resource kind, and a schema goal only an ObjectType.
    assert eligible_kind_mentions(_typed(filtered, _GROUPS)) == {"m1"}
    assert eligible_kind_mentions(_typed(schema, _GROUPS)) == frozenset()
    assert eligible_kind_mentions(_typed(_incidents(), _INCIDENTS)) == {"m1"}


async def test_a_kind_found_only_in_the_sibling_catalog_takes_that_domain() -> None:
    model = _Model([_incidents()], {"m1": ["object:Incident"]})

    observation = await _shadow(model, _INCIDENTS)

    (only_pass,) = observation.passes
    assert only_pass.regrounded == ("m1",)
    (goal,) = observation.compilations[0].goals
    # The incident kind binds, and the unsupported state filter is now what the turn says.
    assert goal.status.value == "unsupported"
    assert goal.reasons == ("filter_unsupported:state",)
    # The stated state is grounded in its own reviewed state catalog.
    assert {shard.domain.value for shard in model.shards} == {
        "resource_type",
        "object_type",
        "state",
    }


async def test_a_kind_found_in_its_stated_catalog_never_reads_the_sibling() -> None:
    model = _Model([_incidents("object_type")], {"m1": ["object:Incident"]})

    observation = await _shadow(model, _INCIDENTS)

    assert observation.passes[0].regrounded == ()
    assert {shard.domain.value for shard in model.shards} == {"object_type", "state"}


async def test_a_kind_neither_catalog_holds_still_clarifies() -> None:
    model = _Model([_incidents()], {})

    observation = await _shadow(model, _INCIDENTS)

    assert observation.passes[0].regrounded == ()
    (goal,) = observation.compilations[0].goals
    assert goal.status.value == "clarify"


async def test_a_contested_kind_binds_only_when_both_choosers_pick_one_lane() -> None:
    picks = {"m1": ["object:Resource", "group:resource-group"]}
    second = {"m1": ["group:resource-group"]}
    agreed = _RunoffModel(
        [_groups()],
        picks,
        second_picks=second,
        runoff=("group:resource-group", "group:resource-group"),
    )
    split = _RunoffModel(
        [_groups()], picks, second_picks=second, runoff=("object:Resource", "group:resource-group")
    )

    bound = await _shadow(agreed, _GROUPS)
    held = await _shadow(split, _GROUPS)

    assert agreed.runoff_calls == 2 and split.runoff_calls == 2
    assert bound.passes[0].regrounded == ("m1",)
    (goal,) = bound.compilations[0].goals
    assert goal.status.value == "compiled"
    assert held.passes[0].regrounded == ()
    (goal,) = held.compilations[0].goals
    assert goal.status.value == "clarify"


_TWO = "List the resource groups and list the resource groups"


def _two_groups() -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": _quote("resource groups"),
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "object_type",
                "span": _quote("resource groups", 2),
            },
        ],
        "goals": [_goal(), _goal(id="g2", subject="m2", cue=_quote("list"))],
        "context": [_quote("the"), _quote("and"), _quote("the", 2)],
    }


async def _budgeted(model: _Model, calls: int) -> Any:
    return await run_reasoning_shadow(
        model=model,
        utterance=_TWO,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        budget=ShadowBudget(max_concept_calls=calls),
    )


async def test_each_cross_lane_runoff_fits_the_turn_concept_budget() -> None:
    def contested() -> _RunoffModel:
        picks = {mention: ["object:Resource", "group:resource-group"] for mention in ("m1", "m2")}
        second = {mention: ["group:resource-group"] for mention in ("m1", "m2")}
        runoff = ("group:resource-group", "group:resource-group")
        return _RunoffModel([_two_groups()], picks, second_picks=second, runoff=runoff)

    open_budget = contested()
    await _budgeted(open_budget, 64)
    needed = len(open_budget.shards) + open_budget.runoff_calls
    tight = contested()
    await _budgeted(tight, needed - 1)

    assert open_budget.runoff_calls == 4
    # Only the runoff the budget still covers runs; the other mention keeps its outcome.
    assert tight.runoff_calls == 2
    assert len(tight.shards) + tight.runoff_calls <= needed - 1


async def test_a_retype_past_the_form_byte_budget_keeps_the_stated_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stated = _typed(_groups(), _GROUPS)
    monkeypatch.setattr(form_module, "MAX_FORM_BYTES", len(stated.canonical_json().encode()))
    model = _Model([_groups()], {"m1": ["group:resource-group"]})

    observation = await _shadow(model, _GROUPS)

    assert observation.passes[0].regrounded == ()
    (goal,) = observation.compilations[0].goals
    assert goal.status.value == "clarify"
