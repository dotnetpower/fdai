"""One bounded repair of a contract-faulted question form, which never drops an operand."""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_repair import FormRepair, repair_keeps_operands

from tests.conversation.test_semantic_reasoning_shadow import (
    _UTTERANCE,
    _adapter,
    _Model,
    _quoted_form,
    _run,
)

_PICKS = {"m2": ["value:compute.vm", "group:compute.vm"]}


def _undeclared_filter() -> dict[str, Any]:
    form = _quoted_form()
    form["goals"][0]["filters"] = [{"role": "type", "mention": "m9"}]
    return form


def _anchorless_relation() -> dict[str, Any]:
    form = _quoted_form()
    form["goals"][0].update(subject="m2", subject_scope="collection", filters=[])
    return form


async def test_a_contract_fault_gets_one_repair_with_authored_violations() -> None:
    model = _Model([_undeclared_filter(), _quoted_form()], _PICKS)

    observation = await _run(model)

    (only_pass,) = observation.passes
    assert only_pass.repair == "applied"
    assert only_pass.repaired_reasons == ("form_contract_invalid:form",)
    assert [goal.status for goal in only_pass.goals] == ["compiled"]
    repair = model.form_calls[1]["repair"]
    assert isinstance(repair, FormRepair)
    assert repair.previous == _undeclared_filter()
    assert repair.violations == ("form: Value error, form goal cites an undeclared mention",)
    assert "m9" not in json.dumps(repair.violations)


async def test_a_structural_admission_fault_is_repaired_once() -> None:
    model = _Model([_anchorless_relation(), _quoted_form()], _PICKS)

    observation = await _run(model)

    assert observation.passes[0].repair == "applied"
    assert observation.passes[0].repaired_reasons == ("relation_anchor_missing:g1",)
    assert model.form_calls[1]["repair"].violations == ("relation_anchor_missing:g1",)
    assert observation.passes[0].disposition == "admitted"


async def test_a_repair_that_drops_a_quoted_operand_is_rejected() -> None:
    dropped = _quoted_form()
    dropped["mentions"] = dropped["mentions"][:1]
    dropped["goals"][0]["filters"] = []
    model = _Model([_undeclared_filter(), dropped], _PICKS)

    observation = await _run(model)

    assert observation.passes[0].disposition == "invalid"
    assert observation.passes[0].repair == "operand_dropped"
    assert observation.passes[0].reasons == ("form_contract_invalid:form",)
    assert observation.compilations == ()


async def test_a_second_fault_stays_invalid_without_another_repair() -> None:
    model = _Model([_undeclared_filter(), _anchorless_relation(), _quoted_form()], _PICKS)

    observation = await _run(model)

    assert len(model.form_calls) == 2
    assert observation.passes[0].disposition == "invalid"
    assert observation.passes[0].reasons == ("relation_anchor_missing:g1",)
    assert observation.passes[0].repair == "applied"


async def test_clarifications_and_disabled_repairs_make_no_second_call() -> None:
    unused = _quoted_form()
    unused["mentions"].append(
        {
            "id": "m3",
            "form": "value",
            "domain": "instance",
            "span": {"text": "what", "occurrence": 1},
        }
    )
    clarify = _Model([unused, _quoted_form()], _PICKS)
    disabled = _Model([_undeclared_filter(), _quoted_form()], _PICKS)

    clarified = await _run(clarify)
    held = await _run(disabled, repairs_per_pass=0)

    assert clarified.passes[0].disposition == "clarify"
    assert clarified.passes[0].repair is None
    assert len(clarify.form_calls) == 1
    assert held.passes[0].disposition == "invalid"
    assert len(disabled.form_calls) == 1


def _resolved(form: dict[str, Any]) -> Any:
    resolved = resolve_question_form(form, utterance=_UTTERANCE).form
    assert resolved is not None
    return resolved


def test_operands_survive_only_when_every_quoted_character_stays_declared() -> None:
    narrowed = _quoted_form()
    narrowed["mentions"][1]["span"] = {"text": "VM", "occurrence": 1}
    widened = _quoted_form()
    widened["mentions"][1]["span"] = {"text": "many VMs", "occurrence": 1}
    unlocated = copy.deepcopy(_quoted_form())
    unlocated["mentions"][1]["span"] = {"text": "virtual machines", "occurrence": 1}
    kinds = _quoted_form()
    kinds["mentions"].append(
        {
            "id": "m3",
            "form": "concept",
            "domain": "declaration_kind",
            "span": {"text": "what", "occurrence": 1},
        }
    )
    one_mention = _quoted_form()
    one_mention["mentions"] = one_mention["mentions"][:1]
    one_mention["goals"][0]["filters"] = []
    single = _resolved(one_mention)

    assert not repair_keeps_operands(_quoted_form(), _resolved(narrowed), utterance=_UTTERANCE)
    assert repair_keeps_operands(_quoted_form(), _resolved(widened), utterance=_UTTERANCE)
    # A declaration kind can change the schema read, so deleting one is never a repair.
    assert not repair_keeps_operands(kinds, _resolved(widened), utterance=_UTTERANCE)
    assert repair_keeps_operands(unlocated, _resolved(widened), utterance=_UTTERANCE)
    assert not repair_keeps_operands(unlocated, single, utterance=_UTTERANCE)
    assert not repair_keeps_operands(_quoted_form(), single, utterance=_UTTERANCE)


def test_goals_operations_times_and_operand_relations_must_survive_a_repair() -> None:
    timed = _quoted_form()
    timed["goals"][0]["time"] = {
        "kind": "window",
        "value": {"duration": {"amount": 3, "unit": "day"}},
        "cue": {"text": "How many", "occurrence": 1},
    }
    second = copy.deepcopy(_quoted_form()["goals"][0])
    second.update(id="g2", operation="traverse", filters=[])
    two_goals = _quoted_form()
    two_goals["goals"].append(second)
    relation_free = _quoted_form()
    relation_free["goals"][0]["relation"] = None
    recounted = _quoted_form()
    recounted["goals"][0]["operation"] = "select"
    anchorless = _anchorless_relation()
    anchorless_dropped = _anchorless_relation()
    anchorless_dropped["goals"][0]["relation"] = None

    assert not repair_keeps_operands(timed, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert not repair_keeps_operands(two_goals, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert not repair_keeps_operands(_quoted_form(), _resolved(relation_free), utterance=_UTTERANCE)
    assert not repair_keeps_operands(_quoted_form(), _resolved(recounted), utterance=_UTTERANCE)
    # A relation with neither anchor nor counterpart on a collection carried no operand.
    assert repair_keeps_operands(anchorless, _resolved(anchorless_dropped), utterance=_UTTERANCE)


async def test_the_adapter_sends_the_rejected_form_and_violations() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(_quoted_form())}}]}
        )

    repair = FormRepair(previous=_undeclared_filter(), violations=("relation_anchor_missing:g1",))
    await _adapter(handler).propose_form(
        utterance=_UTTERANCE,
        context=(),
        locale="en",
        pass_index=0,
        prior_goals=(),
        repair=repair,
    )

    sent = json.loads(captured["messages"][1]["content"])
    assert sent["repair"] == {
        "previous_form": _undeclared_filter(),
        "violations": ["relation_anchor_missing:g1"],
    }


def test_trimming_whitespace_or_dropping_a_restated_time_mention_is_a_valid_repair() -> None:
    padded = _quoted_form()
    padded["mentions"][0]["span"] = {"text": " sql-app", "occurrence": 1}
    timed = _quoted_form()
    timed["goals"][0]["time"] = {
        "kind": "window",
        "value": {"duration": {"amount": 3, "unit": "day"}},
        "cue": {"text": "How many", "occurrence": 1},
    }
    restating = copy.deepcopy(timed)
    restating["mentions"].append(
        {
            "id": "m3",
            "form": "value",
            "domain": "instance",
            "span": {"text": "How many", "occurrence": 1},
        }
    )

    assert repair_keeps_operands(padded, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert repair_keeps_operands(restating, _resolved(timed), utterance=_UTTERANCE)
    assert not repair_keeps_operands(restating, _resolved(_quoted_form()), utterance=_UTTERANCE)
