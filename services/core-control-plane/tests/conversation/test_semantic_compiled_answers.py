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
from fdai.composition.semantic_query_type_grounding import compiled_answers_enabled
from fdai.core.conversation import semantic_compiled_answers
from fdai.core.conversation.semantic_compiled_answers import (
    CompiledAnswerPath,
    CompiledAnswerTicket,
    compiled_answer_or,
    start_compiled_answer,
)
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.semantic_reasoning_compiler import (
    GoalCompilation,
    GoalStatus,
    ReasoningCompilation,
    compile_question_form,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_shadow import ReasoningShadowObservation
from fdai.core.conversation.session import Principal, Role

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
    "overrides",
    [
        {"released": False},
        {"continuation_pending": True},
        {"compilations": ()},
    ],
)
def test_an_unreleased_or_incomplete_path_leaves_the_turn_to_the_current_path(
    overrides: dict[str, Any], caplog: pytest.LogCaptureFixture, events: list[dict[str, Any]]
) -> None:
    recorded: list[Any] = []
    outcome = _ticket(_observation(**overrides)).outcome(
        manifest_digest="sha256:" + "a" * 64, observations=recorded
    )
    assert outcome is None
    assert len(recorded) == 1
    assert _completions(caplog) == ["declined"]


def test_a_second_goal_limitation_or_batch_is_never_answered_as_complete() -> None:
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
    two = _observation(compilations=(compilation, compilation))
    assert _ticket(two).outcome(manifest_digest="d", observations=[]) is None


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


def test_relation_sides_split_across_batches_answer_as_one_plan() -> None:
    compilation = _relation_compilation("one_sense")
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert len(goal.batches) > 1
    outputs = [node for batch in goal.batches for node in batch.plan.output_node_ids]

    outcome = _ticket(_observation(compilations=(compilation,))).outcome(
        manifest_digest="d", observations=[]
    )
    if len(outputs) > 8:
        # One plan names at most eight outputs, so this read is left to the current path.
        assert outcome is None
        fewer = replace(goal, batches=goal.batches[:2])
        fewer = replace(
            fewer,
            batches=tuple(replace(batch, total=2) for batch in fewer.batches),
        )
        outputs = [node for batch in fewer.batches for node in batch.plan.output_node_ids]
        compilation = replace(compilation, goals=(fewer,))
        outcome = _ticket(_observation(compilations=(compilation,))).outcome(
            manifest_digest="d", observations=[]
        )

    assert outcome is not None and outcome.plan is not None
    assert list(outcome.plan.output_node_ids) == outputs
    assert len({node.node_id for node in outcome.plan.nodes}) == len(outcome.plan.nodes)
    assert len(outcome.plan.nodes) <= 16


def test_batches_with_clashing_node_ids_are_declined() -> None:
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
