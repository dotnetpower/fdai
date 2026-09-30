"""Answer a turn from a released question-form compilation, or leave it to the current path."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.composition.semantic_query_type_grounding import (
    compiled_answers_enabled,
    typed_only_enabled,
)
from fdai.core.conversation import semantic_compiled_answers
from fdai.core.conversation.semantic_compiled_answers import (
    CompiledAnswerPath,
    CompiledAnswerTicket,
    compiled_answer_or,
    start_compiled_answer,
    typed_only_outcome,
)
from fdai.core.conversation.semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
    hold_details,
)
from fdai.core.conversation.semantic_reasoning_compiler import (
    GoalCompilation,
    GoalStatus,
    ReasoningCompilation,
    compile_question_form,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_shadow import (
    ReasoningShadowObservation,
    ShadowPass,
)
from fdai.core.conversation.session import Principal, Role
from fdai_service_contracts.ontology_query import (
    MAX_INTENT_GOAL_DEPENDENCIES,
    QueryNodeKind,
    project_intent_graph,
)

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    plan_verifier,
    production_manifest,
    span,
    synthetic_anchors,
)

_UTTERANCE = "List the VMs"
_LATER = NOW + timedelta(seconds=40)


def _compilation() -> ReasoningCompilation:
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(_UTTERANCE, "VMs"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": span(_UTTERANCE, "List"),
                "confidence": 0.93,
            }
        ],
    }
    admission = admitted(form, _UTTERANCE)
    compilation = compile_question_form(
        admission,
        concepts=concepts(("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",))),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_UTTERANCE,
        anchors=synthetic_anchors(admission),
    )
    assert compilation.goals[0].status is GoalStatus.COMPILED
    return compilation


def _observation(**overrides: Any) -> ReasoningShadowObservation:
    values: dict[str, Any] = {
        "passes": (),
        "model_calls": 4,
        "elapsed_ms": 1200,
        "continuation_pending": False,
        "released": True,
        "review": "faithful",
        "compilations": (_compilation(),),
    }
    values.update(overrides)
    return ReasoningShadowObservation(**values)


def _ticket(result: Any, *, deadline: float = 5.0) -> CompiledAnswerTicket:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    if isinstance(result, BaseException):
        future.set_exception(result)
    elif result is not None:
        future.set_result(result)
    collector = semantic_compiled_answers._ObservationCollector()
    collector.observations.append(SimpleNamespace(model="form-model"))  # type: ignore[arg-type]
    return CompiledAnswerTicket(
        future,
        collector,
        deadline_seconds=deadline,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        cutoff=lambda: _LATER,
    )


@pytest.fixture
def events(caplog: pytest.LogCaptureFixture) -> Iterator[list[dict[str, Any]]]:
    caplog.set_level(logging.INFO, logger="fdai.core.conversation.semantic_compiled_answers")
    captured: list[dict[str, Any]] = []
    yield captured


def _completions(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.result
        for record in caplog.records
        if record.msg == "semantic_compiled_answer_completed"
    ]


def _decline_reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.decline_reason
        for record in caplog.records
        if record.msg == "semantic_compiled_answer_completed" and record.result == "declined"
    ]


def test_a_released_single_goal_answers_with_a_fresh_cutoff(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    observation = _observation()
    original = observation.compilations[0].goals[0].batches[0].plan
    recorded: list[Any] = []

    outcome = _ticket(observation).outcome(
        manifest_digest="sha256:" + "a" * 64, observations=recorded
    )

    assert outcome is not None
    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None and outcome.intent_graph is not None
    assert outcome.plan.plan_digest != original.plan_digest
    definition = json.loads(outcome.plan.nodes[0].arguments_json)["definition"]
    assert definition["as_of"] == _LATER.isoformat()
    assert [item.model for item in recorded] == ["form-model"]
    assert _completions(caplog) == ["selected"]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"released": False}, "not_released"),
        ({"continuation_pending": True}, "continuation_pending"),
        ({"compilations": ()}, "compilation_count"),
    ],
)
def test_an_unreleased_or_incomplete_path_leaves_the_turn_to_the_current_path(
    overrides: dict[str, Any],
    reason: str,
    caplog: pytest.LogCaptureFixture,
    events: list[dict[str, Any]],
) -> None:
    recorded: list[Any] = []
    outcome = _ticket(_observation(**overrides)).outcome(
        manifest_digest="sha256:" + "a" * 64, observations=recorded
    )
    assert outcome is None
    assert len(recorded) == 1
    assert _completions(caplog) == ["declined"]
    assert _decline_reasons(caplog) == [reason]


def test_a_second_goal_limitation_or_batch_is_never_answered_as_complete(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _compilation()
    goal = compilation.goals[0]
    sibling = GoalCompilation("g2", GoalStatus.UNSUPPORTED, ("operation_unsupported:rank",))
    variants = (
        replace(compilation, goals=(goal, sibling)),
        replace(compilation, goals=(replace(goal, limitations=("prior_result_truncated",)),)),
        replace(compilation, goals=(replace(goal, batches=(*goal.batches, *goal.batches)),)),
        replace(compilation, needs_continuation=True),
    )
    for variant in variants:
        observation = _observation(compilations=(variant,))
        assert _ticket(observation).outcome(manifest_digest="d", observations=[]) is None
    two = _observation(
        compilations=(compilation, compilation),
        passes=(ShadowPass(0, "admitted", shape=("m1:instance:name", "g1:instance:count:anchor")),),
    )
    assert _ticket(two).outcome(manifest_digest="d", observations=[]) is None
    shapes = [
        record.form_shapes
        for record in caplog.records
        if record.msg == "semantic_compiled_answer_completed"
    ]
    # The last pass's content-free shape shows how the declined question was read.
    assert shapes[-1] == ["m1:instance:name", "g1:instance:count:anchor"]
    assert shapes[0] == []
    # Every decline names the one rule that kept the compilation from answering.
    assert _decline_reasons(caplog) == [
        "goal_count",
        "goal_limited",
        "batch_order",
        "continuation_pending",
        "compilation_count",
    ]


def _unsupported_observation(*, released: bool = True) -> ReasoningShadowObservation:
    compilation = _compilation()
    goal = GoalCompilation("g1", GoalStatus.UNSUPPORTED, ("filter_unsupported:region",))
    return _observation(released=released, compilations=(replace(compilation, goals=(goal,)),))


@pytest.mark.parametrize(
    "plan_source", ["server_stated_filter", "server_resource_target_candidates"]
)
def test_a_released_unsupported_reading_holds_a_word_recovered_plan(
    plan_source: str, caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    ticket = _ticket(_unsupported_observation())
    assert ticket.outcome(manifest_digest="d", observations=[]) is None

    vetoed = ticket.veto(plan_source, manifest_digest="d")

    # The reviewed reading states a region the filter recovered from words would drop.
    assert vetoed is not None
    assert vetoed.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert vetoed.reason == "semantic_stated_constraint_unsupported"
    vetoes = [r for r in caplog.records if r.msg == "semantic_compiled_answer_veto"]
    assert [record.goal_reasons for record in vetoes] == [["filter_unsupported:region"]]


def test_a_data_outcome_never_holds_but_a_wider_parsed_reading_does() -> None:
    compilation = _compilation()
    incomplete = GoalCompilation("g1", GoalStatus.UNSUPPORTED, ("anchor_resolution_incomplete",))
    data = _ticket(_observation(compilations=(replace(compilation, goals=(incomplete,)),)))
    data.outcome(manifest_digest="d", observations=[])
    grouped = _ticket(
        _observation(
            released=False,
            passes=(ShadowPass(0, "clarify", shape=("reading:beyond_list", "m1:instance:name")),),
        )
    )
    grouped.outcome(manifest_digest="d", observations=[])
    listed = _ticket(
        _observation(released=False, passes=(ShadowPass(0, "invalid", shape=("reading:list",)),))
    )
    listed.outcome(manifest_digest="d", observations=[])

    # An incomplete anchor read is about data, not about what the question states.
    assert data.veto("server_stated_filter", manifest_digest="d") is None
    held = grouped.veto("server_stated_filter", manifest_digest="d")
    assert held is not None and held.reason == "semantic_stated_constraint_unsupported"
    assert listed.veto("server_stated_filter", manifest_digest="d") is None


def test_a_typed_plan_or_an_unreleased_reading_is_never_held() -> None:
    released = _ticket(_unsupported_observation())
    released.outcome(manifest_digest="d", observations=[])
    unreleased = _ticket(_unsupported_observation(released=False))
    unreleased.outcome(manifest_digest="d", observations=[])
    unconsumed = _ticket(_unsupported_observation())

    # A typed builder reads its own stated atoms, and an unreviewed reading holds nothing.
    assert released.veto("server_recent_resource_changes", manifest_digest="d") is None
    assert unreleased.veto("server_stated_filter", manifest_digest="d") is None
    assert unconsumed.veto("server_stated_filter", manifest_digest="d") is None


def test_a_timeout_or_failure_cancels_the_path_and_consumes_the_ticket_once(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    pending = _ticket(None, deadline=1.0)
    pending._deadline = 0.0  # noqa: SLF001 - the deadline has already passed
    assert pending.outcome(manifest_digest="d", observations=[]) is None
    assert pending._future.cancelled()  # noqa: SLF001
    failing = _ticket(RuntimeError("provider down"))
    assert failing.outcome(manifest_digest="d", observations=[]) is None
    assert failing.outcome(manifest_digest="d", observations=[]) is None
    assert _completions(caplog) == ["timeout", "failed"]


def test_cancel_records_one_event_and_ends_the_ticket(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    ticket = _ticket(None)
    ticket.cancel()
    ticket.cancel()
    assert ticket._future.cancelled()  # noqa: SLF001
    assert ticket.outcome(manifest_digest="d", observations=[]) is None
    assert _completions(caplog) == ["cancelled"]


def test_a_hold_is_replaced_only_by_a_released_compilation() -> None:
    hold = SimpleNamespace(disposition=SemanticPlanningDisposition.UNAVAILABLE)
    assert compiled_answer_or(None, hold, manifest_digest="d", observations=[]) is hold  # type: ignore[arg-type]
    declined = _ticket(_observation(released=False))
    assert compiled_answer_or(declined, hold, manifest_digest="d", observations=[]) is hold  # type: ignore[arg-type]
    released = _ticket(_observation())
    answer = compiled_answer_or(released, hold, manifest_digest="d", observations=[])  # type: ignore[arg-type]
    assert answer.disposition is SemanticPlanningDisposition.PLANNED


def test_the_path_runs_on_the_owner_loop_with_executor_scoped_anchor_reads(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    seen: dict[str, Any] = {}

    async def fake_shadow(**arguments: Any) -> ReasoningShadowObservation:
        seen.update(arguments)
        return _observation()

    monkeypatch.setattr(semantic_compiled_answers, "run_reasoning_shadow", fake_shadow)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        path = CompiledAnswerPath(
            model=SimpleNamespace(),  # type: ignore[arg-type]
            owner_loop=loop,
            gateway=SimpleNamespace(),  # type: ignore[arg-type]
            purpose=PURPOSE,
            clock=lambda: _LATER,
        )
        arguments = {
            "utterance": _UTTERANCE,
            "context": (),
            "locale": "en",
            "manifest": production_manifest(),
            "verifier": plan_verifier(),
            "purpose": PURPOSE,
        }
        reader = Principal(id="operator", role=Role.READER)
        assert start_compiled_answer(path, eligible=False, principal=reader, **arguments) is None
        assert path.start(principal=reader, **{**arguments, "purpose": "other"}) is None
        ticket = path.start(principal=reader, **arguments)
        assert ticket is not None
        outcome = ticket.outcome(manifest_digest="d", observations=[])
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
    assert outcome is not None
    assert seen["retain_compilations"] is True
    assert seen["evaluation_time"] == _LATER
    request = seen["resolver"]._request  # noqa: SLF001
    assert request.caller_role.value == "reader"
    assert request.declared_purposes == frozenset({PURPOSE})
    assert request.principal_scope_digest is not None
    assert _completions(caplog) == ["skipped", "selected"]


def test_compiled_answers_are_composed_only_in_the_local_venue() -> None:
    assert compiled_answers_enabled(
        {"FDAI_SEMANTIC_COMPILED_ANSWERS": "1", "FDAI_EXECUTION_VENUE": "local"}
    )
    assert not compiled_answers_enabled({"FDAI_SEMANTIC_COMPILED_ANSWERS": "1"})
    assert not compiled_answers_enabled(
        {"FDAI_SEMANTIC_COMPILED_ANSWERS": "1", "FDAI_EXECUTION_VENUE": "deployed"}
    )
    assert not compiled_answers_enabled({"FDAI_EXECUTION_VENUE": "local"})


def test_typed_only_answering_needs_its_whole_path_or_refuses_to_start() -> None:
    complete = {
        "FDAI_SEMANTIC_TYPED_ONLY": "1",
        "FDAI_SEMANTIC_SECOND_READER": "1",
        "FDAI_SEMANTIC_COMPILED_ANSWERS": "1",
        "FDAI_EXECUTION_VENUE": "local",
    }

    assert typed_only_enabled(complete)
    assert not typed_only_enabled(
        {key: value for key, value in complete.items() if "TYPED" not in key}
    )
    # Without the form path a typed-only read would silently answer from the legacy path.
    for missing in ("FDAI_SEMANTIC_SECOND_READER", "FDAI_SEMANTIC_COMPILED_ANSWERS"):
        with pytest.raises(ValueError, match="typed-only"):
            typed_only_enabled({key: value for key, value in complete.items() if key != missing})
    with pytest.raises(ValueError, match="typed-only"):
        typed_only_enabled({**complete, "FDAI_EXECUTION_VENUE": "deployed"})


def _relation_compilation(scope: str) -> ReasoningCompilation:
    from tests.conversation.test_semantic_reasoning_compiler import _compile, _relation_form

    utterance = "What is connected to aks-prod-01?"
    return _compile(
        utterance,
        _relation_form(
            utterance,
            anchor="aks-prod-01",
            sense="connectivity",
            position="either",
            cue="connected to",
            scope=scope,
        ),
    )


def test_relation_sides_split_across_batches_answer_as_one_plan(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _relation_compilation("one_sense")
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert len(goal.batches) > 1
    fewer = replace(
        goal,
        batches=tuple(replace(batch, total=2) for batch in goal.batches[:2]),
    )
    outputs = [node for batch in fewer.batches for node in batch.plan.output_node_ids]

    outcome = _ticket(_observation(compilations=(replace(compilation, goals=(fewer,)),))).outcome(
        manifest_digest="d", observations=[]
    )

    assert outcome is not None and outcome.plan is not None
    assert list(outcome.plan.output_node_ids) == outputs
    assert len({node.node_id for node in outcome.plan.nodes}) == len(outcome.plan.nodes)
    assert len(outcome.plan.nodes) <= 16


def test_sides_beyond_eight_outputs_are_united_so_none_is_dropped(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _relation_compilation("one_sense")
    goal = compilation.goals[0]
    sides = [node for batch in goal.batches for node in batch.plan.output_node_ids]
    assert len(sides) > 8

    outcome = _ticket(_observation(compilations=(compilation,))).outcome(
        manifest_digest="d", observations=[]
    )

    # One plan names at most eight outputs; every side is still read and each reached
    # endpoint type becomes one union output, verified and aligned like any other plan.
    assert outcome is not None and outcome.plan is not None
    unions = [node for node in outcome.plan.nodes if node.kind is QueryNodeKind.UNION]
    roots = [node.node_id for node in unions if node.node_id in outcome.plan.output_node_ids]
    assert roots == list(outcome.plan.output_node_ids)
    union_ids = {node.node_id for node in unions}
    read = [item for node in unions for item in node.depends_on if item not in union_ids]
    assert sorted(read) == sorted(sides)
    # No union reads more dependencies than one Console intent goal can show.
    assert all(len(node.depends_on) <= MAX_INTENT_GOAL_DEPENDENCIES for node in unions)
    assert outcome.intent_graph is not None
    assert project_intent_graph(outcome.intent_graph)["goals"]
    assert len(outcome.plan.nodes) <= 16
    assert _completions(caplog) == ["selected"]


def test_a_relation_read_beyond_one_intent_graph_is_declined_as_over_budget(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _relation_compilation("all_kinds")
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert sum(len(batch.plan.output_node_ids) for batch in goal.batches) > 15

    outcome = _ticket(_observation(compilations=(compilation,))).outcome(
        manifest_digest="d", observations=[]
    )

    assert outcome is None
    assert _decline_reasons(caplog) == ["merge_over_budget"]


def test_batches_with_clashing_node_ids_are_declined(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _relation_compilation("one_sense")
    goal = compilation.goals[0]
    first, second = goal.batches[0], goal.batches[1]
    clashing = second.plan.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"arguments_json": node.arguments_json.replace("1", "2")})
                if node.node_id in {item.node_id for item in first.plan.nodes}
                else node
                for node in second.plan.nodes
            )
        }
    )
    broken = replace(goal, batches=(first, replace(second, plan=clashing), *goal.batches[2:]))
    observation = _observation(compilations=(replace(compilation, goals=(broken,)),))

    assert _ticket(observation).outcome(manifest_digest="d", observations=[]) is None
    assert _decline_reasons(caplog) == ["merge_node_conflict"]


@pytest.mark.parametrize(
    ("observation", "decision"),
    [
        (_observation(released=False, passes=()), "unavailable"),
        (
            _observation(
                released=False, passes=(ShadowPass(0, "clarify", ("competing_reading:g1",)),)
            ),
            "clarification",
        ),
        (_observation(released=False, passes=(ShadowPass(0, "invalid"),)), "unverified"),
        (
            _observation(released=False, review="unfaithful", passes=(ShadowPass(0, "admitted"),)),
            "unverified",
        ),
        (_observation(continuation_pending=True), "continuation"),
        # A reading that still needs a pass is never released, yet it is a continuation.
        (
            _observation(
                released=False,
                continuation_pending=True,
                passes=(ShadowPass(0, "admitted"), ShadowPass(1, "generation_changed")),
            ),
            "continuation",
        ),
    ],
)
def test_every_declined_path_ends_with_one_tagged_decision(
    observation: ReasoningShadowObservation, decision: str
) -> None:
    ticket = _ticket(observation)
    assert ticket.outcome(manifest_digest="d", observations=[]) is None
    assert ticket.decision == decision


def test_typed_only_maps_each_decision_to_one_typed_outcome() -> None:
    unsupported = _ticket(_unsupported_observation())
    unsupported.outcome(manifest_digest="d", observations=[])
    limited_goal = replace(_compilation().goals[0], limitations=("time_window_applied:3600",))
    limited = _ticket(_observation(compilations=(replace(_compilation(), goals=(limited_goal,)),)))
    limited.outcome(manifest_digest="d", observations=[])
    timed_out = _ticket(None, deadline=1.0)
    timed_out._deadline = 0.0  # noqa: SLF001 - the deadline has already passed
    timed_out.outcome(manifest_digest="d", observations=[])

    outcomes = {
        name: typed_only_outcome(ticket, manifest_digest="d")
        for name, ticket in (
            ("unsupported", unsupported),
            ("limited", limited),
            ("timeout", timed_out),
        )
    }

    assert outcomes["unsupported"].disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcomes["unsupported"].reason == "semantic_stated_constraint_unsupported"
    assert outcomes["limited"].reason == "semantic_reading_limited"
    assert outcomes["timeout"].reason == "semantic_reading_unavailable"
    # A turn whose form path never started is unavailable, never a legacy answer.
    assert typed_only_outcome(None, manifest_digest="d").reason == "semantic_reading_unavailable"


def test_a_typed_only_hold_replaces_the_judgment_hold_and_a_cancel_is_superseded() -> None:
    hold = SemanticPlanningOutcome(
        disposition=SemanticPlanningDisposition.UNAVAILABLE, reason="judgment_hold"
    )
    ticket = _ticket(_unsupported_observation())
    ticket.typed_only = True
    replaced = compiled_answer_or(ticket, hold, manifest_digest="d", observations=[])
    cancelled = _ticket(_observation())
    cancelled.cancel()

    assert replaced.reason == "semantic_stated_constraint_unsupported"
    assert cancelled.decision == "superseded"


def _cause_compilation() -> ReasoningCompilation:
    from tests.conversation.test_semantic_reasoning_compiler import _cause_form, _compile

    utterance = "Why is vm-app-01 stopped?"
    return _compile(utterance, _cause_form(utterance))


def test_a_compilation_answers_with_the_limitations_its_frame_states(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _cause_compilation()

    outcome = _ticket(_observation(compilations=(compilation,))).outcome(
        manifest_digest="d", observations=[]
    )

    # The cause-not-established and window limitations are stated as reviewed notices.
    assert outcome is not None and outcome.frame is not None
    assert outcome.frame.output_shape == "cause_context"
    assert "cause.not_established" in outcome.frame.evidence_requirements
    assert _completions(caplog) == ["selected"]


def test_a_limitation_no_notice_states_keeps_the_compilation_from_answering(
    caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    compilation = _cause_compilation()
    goal = compilation.goals[0]
    unstated = replace(goal, limitations=(*goal.limitations, "prior_result_truncated"))
    ticket = _ticket(_observation(compilations=(replace(compilation, goals=(unstated,)),)))

    assert ticket.outcome(manifest_digest="d", observations=[]) is None
    assert _decline_reasons(caplog) == ["goal_limited"]
    assert ticket.decision == "limited"


def test_a_data_outcome_is_unavailable_and_an_unsupported_atom_is_unsupported() -> None:
    compilation = _compilation()
    incomplete = GoalCompilation("g1", GoalStatus.UNSUPPORTED, ("anchor_resolution_incomplete",))
    data = _ticket(_observation(compilations=(replace(compilation, goals=(incomplete,)),)))
    data.outcome(manifest_digest="d", observations=[])
    atom = _ticket(_unsupported_observation())
    atom.outcome(manifest_digest="d", observations=[])

    # An incomplete anchor read says nothing about what the question asks.
    assert data.decision == "unavailable"
    assert atom.decision == "unsupported"


def test_a_typed_hold_carries_the_closed_codes_that_say_why() -> None:
    atom = _ticket(_unsupported_observation())
    atom.outcome(manifest_digest="d", observations=[])
    review = _ticket(
        _observation(
            released=False,
            review="unfaithful",
            review_reasons=("review_uncovered:times:4-12", "review_merged:0-3"),
            passes=(ShadowPass(0, "admitted"),),
        )
    )
    review.outcome(manifest_digest="d", observations=[])
    clarified = _ticket(
        _observation(released=False, passes=(ShadowPass(0, "clarify", ("competing_reading:g1",)),))
    )
    clarified.outcome(manifest_digest="d", observations=[])

    unsupported = typed_only_outcome(atom, manifest_digest="d")
    unverified = typed_only_outcome(review, manifest_digest="d")
    ambiguous = typed_only_outcome(clarified, manifest_digest="d")

    assert unsupported.hold_details == ("filter_unsupported:region",)
    # A review reason keeps only its constraint role; a quote position never travels.
    assert unverified.reason == "semantic_reading_unverified"
    assert unverified.hold_details == ("role:times", "review_merged")
    assert ambiguous.hold_details == ("competing_reading",)
    # A word-recovered plan held by a released reading names the atom it cannot read.
    vetoed = atom.veto("server_stated_filter", manifest_digest="d")
    assert vetoed is not None and vetoed.hold_details == ("filter_unsupported:region",)


def test_hold_details_stay_closed_codes_on_held_outcomes_only() -> None:
    kept = hold_details(("role:times", "role:times", "free text!", "filter_unsupported:state"))

    assert kept == ("role:times", "filter_unsupported:state")
    with pytest.raises(ValueError, match="closed codes"):
        SemanticPlanningOutcome(
            disposition=SemanticPlanningDisposition.UNAVAILABLE,
            reason="semantic_reading_ambiguous",
            hold_details=("Operator Words",),
        )
    with pytest.raises(ValueError, match="held or unsupported"):
        SemanticPlanningOutcome(
            disposition=SemanticPlanningDisposition.CLARIFICATION,
            reason="semantic_clarification_required",
            clarification="Which one?",
            hold_details=("role:times",),
        )


async def test_a_failed_form_is_read_once_more_and_never_more_than_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = _observation(released=False, passes=(ShadowPass(0, "invalid"),), compilations=())
    samples = [invalid, _observation()]
    calls: list[int] = []

    async def shadow(**_arguments: Any) -> ReasoningShadowObservation:
        calls.append(1)
        return samples.pop(0)

    monkeypatch.setattr(semantic_compiled_answers, "run_reasoning_shadow", shadow)
    collector = semantic_compiled_answers._ObservationCollector()

    result = await semantic_compiled_answers._run_form_path(object(), collector)  # type: ignore[arg-type]

    # The second sample passes the same release and selection rules as the first.
    assert len(calls) == 2
    assert result.released and "form_resampled" in result.notes
    assert result.model_calls == invalid.model_calls + 4


async def test_an_answerable_or_unsupported_reading_is_never_resampled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    samples = {"answerable": _observation(), "unsupported": _unsupported_observation()}

    for name, first in samples.items():

        async def shadow(
            _first: ReasoningShadowObservation = first, _name: str = name, **_arguments: Any
        ) -> ReasoningShadowObservation:
            calls.append(_name)
            return _first

        monkeypatch.setattr(semantic_compiled_answers, "run_reasoning_shadow", shadow)
        collector = semantic_compiled_answers._ObservationCollector()
        await semantic_compiled_answers._run_form_path(object(), collector)  # type: ignore[arg-type]

    # An unsupported atom stays unsupported in any sample, so no call is spent on it.
    assert calls == ["answerable", "unsupported"]


async def test_a_reading_that_needs_another_pass_is_never_resampled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _observation(
        released=False, continuation_pending=True, passes=(ShadowPass(0, "admitted"),)
    )
    calls: list[int] = []

    async def shadow(**_arguments: Any) -> ReasoningShadowObservation:
        calls.append(1)
        return pending

    monkeypatch.setattr(semantic_compiled_answers, "run_reasoning_shadow", shadow)
    collector = semantic_compiled_answers._ObservationCollector()

    result = await semantic_compiled_answers._run_form_path(object(), collector)  # type: ignore[arg-type]

    # A continuation is not a failed form, so a second sample would only repeat it.
    assert calls == [1] and result is pending
