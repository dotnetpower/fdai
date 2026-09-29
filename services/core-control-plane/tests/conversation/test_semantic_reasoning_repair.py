"""One bounded repair of a contract-faulted question form, which never drops an operand."""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_repair import (
    FormRepair,
    _violation,
    repair_keeps_operands,
)

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
    # The recorded reason stays a code; the model sees the rule that code breaks.
    (violation,) = model.form_calls[1]["repair"].violations
    assert violation.startswith("relation_anchor_missing: goal g1 has a relation with no")
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
    assert repair_keeps_operands(
        restating, _resolved(timed), utterance=_UTTERANCE, typed=_resolved(restating)
    )
    assert not repair_keeps_operands(
        restating, _resolved(_quoted_form()), utterance=_UTTERANCE, typed=_resolved(restating)
    )
    # Without the closed schema's reading, no time restatement can excuse a dropped quote.
    assert not repair_keeps_operands(restating, _resolved(timed), utterance=_UTTERANCE)


def test_a_cited_operand_never_counts_as_a_restated_time() -> None:
    timed = _quoted_form()
    timed["goals"][0]["time"] = {
        "kind": "window",
        "value": {"duration": {"amount": 3, "unit": "day"}},
        "cue": {"text": "sql-app", "occurrence": 1},
    }
    unanchored = copy.deepcopy(timed)
    unanchored["mentions"] = unanchored["mentions"][1:]
    unanchored["goals"][0].update(subject="m2", subject_scope="collection", filters=[])
    unanchored["goals"][0]["relation"]["anchor"] = None

    assert not repair_keeps_operands(
        timed, _resolved(unanchored), utterance=_UTTERANCE, typed=_resolved(timed)
    )


_FLIPPED = [
    {
        "goal": "g1",
        "atoms": [
            {"field": "relation.anchor_role", "value": "dependent"},
            {"field": "relation.result_role", "value": "dependency"},
        ],
    }
]


def test_competing_readings_pending_goals_and_wants_must_survive_a_repair() -> None:
    ambiguous = _quoted_form(alternatives=_FLIPPED)
    pending = _quoted_form(remaining_goals=True)
    causal = _quoted_form()
    causal["goals"][0]["want"] = "cause"

    assert not repair_keeps_operands(ambiguous, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert repair_keeps_operands(ambiguous, _resolved(ambiguous), utterance=_UTTERANCE)
    assert not repair_keeps_operands(pending, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert repair_keeps_operands(pending, _resolved(pending), utterance=_UTTERANCE)
    assert not repair_keeps_operands(causal, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert not repair_keeps_operands(_quoted_form(), _resolved(causal), utterance=_UTTERANCE)
    assert repair_keeps_operands(causal, _resolved(causal), utterance=_UTTERANCE)


async def test_a_repair_that_drops_a_competing_reading_is_rejected() -> None:
    faulted = _undeclared_filter()
    faulted["alternatives"] = _FLIPPED
    faulted["remaining_goals"] = True
    model = _Model([faulted, _quoted_form()], _PICKS)

    observation = await _run(model)

    assert observation.passes[0].repair == "operand_dropped"
    assert observation.passes[0].disposition == "invalid"
    assert observation.compilations == ()


def test_caution_compares_the_typed_reading_that_the_schema_normalizes() -> None:
    numeric = _anchorless_relation()
    numeric["remaining_goals"] = 1
    typed = _resolved(numeric)
    fixed = _quoted_form()
    kept = _quoted_form(remaining_goals=True)

    assert typed.remaining_goals is True
    assert not repair_keeps_operands(numeric, _resolved(fixed), utterance=_UTTERANCE, typed=typed)
    assert repair_keeps_operands(numeric, _resolved(kept), utterance=_UTTERANCE, typed=typed)


def test_an_unparsed_proposal_keeps_any_pending_value_and_fails_closed_on_its_want() -> None:
    textual = _undeclared_filter()
    textual["remaining_goals"] = "true"
    unreadable = _undeclared_filter()
    unreadable["goals"][0]["want"] = "why"
    stated = _undeclared_filter()
    stated["goals"][0]["want"] = "fact"
    malformed = _undeclared_filter()
    malformed["goals"][0]["id"] = ["g1"]
    malformed["alternatives"] = [{"goal": ["g1"]}, "g1"]

    assert not repair_keeps_operands(textual, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert not repair_keeps_operands(unreadable, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert repair_keeps_operands(stated, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert not repair_keeps_operands(malformed, _resolved(_quoted_form()), utterance=_UTTERANCE)


async def test_a_repair_that_drops_a_normalized_pending_signal_is_rejected() -> None:
    pending = _anchorless_relation()
    pending["remaining_goals"] = 1
    model = _Model([pending, _quoted_form()], _PICKS)

    observation = await _run(model)

    assert observation.passes[0].repair == "operand_dropped"
    assert observation.passes[0].disposition == "invalid"


@pytest.mark.parametrize("value", (0, 0.0, "false", [], {}))
def test_an_unparsed_proposal_keeps_even_a_falsy_stated_pending_value(value: object) -> None:
    unparsed = _undeclared_filter()
    unparsed["remaining_goals"] = value
    kept = _resolved(_quoted_form(remaining_goals=True))

    assert not repair_keeps_operands(unparsed, _resolved(_quoted_form()), utterance=_UTTERANCE)
    assert repair_keeps_operands(unparsed, kept, utterance=_UTTERANCE)


@pytest.mark.parametrize("value", (False, None))
def test_an_unparsed_explicit_false_or_null_is_not_pending(value: object) -> None:
    unparsed = _undeclared_filter()
    unparsed["remaining_goals"] = value

    assert repair_keeps_operands(unparsed, _resolved(_quoted_form()), utterance=_UTTERANCE)


def _reshaped(field: str) -> dict[str, Any]:
    form = _undeclared_filter()
    goal = form["goals"][0]
    if field == "goals":
        form["goals"] = goal
    elif field == "mentions":
        form["mentions"] = form["mentions"][0]
    elif field == "duplicate_id":
        twin = copy.deepcopy(goal)
        twin.update(level="schema", cue={"text": "what", "occurrence": 1})
        form["goals"].append(twin)
    elif field == "operation":
        goal["operation"] = {"value": "count"}
    elif field == "time":
        goal["time"] = [{"kind": "window", "value": {"duration": {"amount": 3, "unit": "day"}}}]
    elif field == "relation":
        goal["relation"] = [goal["relation"]]
    return form


@pytest.mark.parametrize(
    "field", ("goals", "mentions", "duplicate_id", "operation", "time", "relation")
)
def test_an_unparsed_proposal_whose_compared_fields_lose_their_shape_fails_closed(
    field: str,
) -> None:
    repaired = _resolved(_quoted_form())

    assert repair_keeps_operands(_undeclared_filter(), repaired, utterance=_UTTERANCE)
    assert not repair_keeps_operands(_reshaped(field), repaired, utterance=_UTTERANCE)


def test_an_unreadable_subject_scope_keeps_its_relation() -> None:
    unscoped = _undeclared_filter()
    unscoped["goals"][0]["subject_scope"] = "somewhere"
    relation_free = _quoted_form()
    relation_free["goals"][0]["relation"] = None

    assert not repair_keeps_operands(unscoped, _resolved(relation_free), utterance=_UTTERANCE)
    assert repair_keeps_operands(unscoped, _resolved(_quoted_form()), utterance=_UTTERANCE)


@pytest.mark.parametrize(
    ("field", "value"),
    (("goals", None), ("goals", []), ("goals", "missing"), ("mentions", None)),
)
def test_unparsed_collections_are_read_as_the_closed_schema_reads_them(
    field: str, value: object
) -> None:
    unreadable = _undeclared_filter()
    if value == "missing":
        del unreadable[field]
    else:
        unreadable[field] = value
    omitted_mentions = _undeclared_filter()
    del omitted_mentions["mentions"]
    omitted_mentions["goals"][0]["filters"] = [{"role": "type", "mention": "m9"}]
    repaired = _resolved(_quoted_form())

    assert not repair_keeps_operands(unreadable, repaired, utterance=_UTTERANCE)
    # Omitted mentions are the schema's empty default, so the goals still bind the repair.
    assert repair_keeps_operands(omitted_mentions, repaired, utterance=_UTTERANCE)


def test_a_repair_never_moves_an_exact_lookup_key() -> None:
    utterance = "aks-prod-01은 무엇에 의존하나요?"

    def form(name: str) -> dict[str, Any]:
        return {
            "mentions": [
                {
                    "id": "m1",
                    "form": "name",
                    "domain": "instance",
                    "span": {"text": name, "occurrence": 1},
                }
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "traverse",
                    "subject": "m1",
                    "subject_scope": "anchor",
                    "relation": {
                        "sense": "dependency",
                        "anchor_role": "dependent",
                        "result_role": "dependency",
                        "cue": {"text": "의존하나요", "occurrence": 1},
                    },
                    "cue": {"text": "무엇에", "occurrence": 1},
                    "confidence": 0.9,
                }
            ],
        }

    typed = resolve_question_form(form("aks-prod-01"), utterance=utterance).form
    widened = resolve_question_form(form("aks-prod-01은"), utterance=utterance).form
    assert typed is not None and widened is not None
    previous = form("aks-prod-01")

    assert repair_keeps_operands(previous, typed, utterance=utterance, typed=typed)
    assert not repair_keeps_operands(previous, widened, utterance=utterance, typed=typed)
    assert not repair_keeps_operands(
        previous, widened, utterance=utterance, typed=typed, extension_only=True
    )


def test_an_admission_violation_is_shown_as_the_rule_it_breaks() -> None:
    fragment = _violation("filter_domain:g1:name_fragment", "Which resources have hub in them?")
    anchorless = _violation("relation_anchor_missing:g1", "")
    unknown = _violation("time_value_mismatch:g1", "")
    qualified = _violation("qualifier_not_instance:m1", "")

    assert fragment.startswith("filter_domain: goal g1 has a name_fragment filter")
    assert "needs a mention with domain instance" in fragment
    assert anchorless.startswith("relation_anchor_missing: goal g1 has a relation with no")
    assert unknown == "time_value_mismatch:g1"
    assert qualified.startswith("qualifier_not_instance: mention m1 has a qualifier")
    assert "as a filter" in qualified
