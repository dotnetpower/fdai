"""A health lookup and a state history of one bound Resource read reviewed shapes only."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_verification import verify_goal_semantics
from fdai.core.conversation.semantic_target_health import TARGET_HEALTH_WINDOW
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
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


def _form(
    utterance: str, *, operation: str, measure: str, time: dict[str, Any] | None = None
) -> dict[str, Any]:
    goal: dict[str, Any] = {
        "id": "g1",
        "level": "instance",
        "operation": operation,
        "subject": "m1",
        "subject_scope": "anchor",
        "measure": {"kind": measure},
        "cue": span(utterance, "vm-app-01"),
        "confidence": 0.9,
    }
    if time is not None:
        goal["time"] = time
    return {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, "vm-app-01")}
        ],
        "goals": [goal],
    }


def _compile(utterance: str, form: dict[str, Any], *, unbound: tuple[str, ...] = ()) -> Any:
    admission = admitted(form, utterance)
    return admission, compile_question_form(
        admission,
        concepts=concepts(),
        manifest=production_manifest(unbound=unbound),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )


def _violations(admission: Any, plan: OntologyQueryPlan) -> tuple[str, ...]:
    return verify_goal_semantics(
        admission.form.goals[0],
        admission=admission,
        concepts=concepts(),
        descriptors=production_manifest().descriptors,
        plans=(plan,),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        anchors=synthetic_anchors(admission),
        evaluation_time=NOW,
    )


def _rewrite(plan: OntologyQueryPlan, node_id: str, update: Any) -> OntologyQueryPlan:
    nodes = []
    for node in plan.nodes:
        if node.node_id == node_id:
            arguments = json.loads(node.arguments_json)
            update(arguments)
            node = node.model_copy(update={"arguments_json": canonical_json(arguments)})
        nodes.append(node)
    return _with_nodes(plan, tuple(nodes))


def _with_nodes(
    plan: OntologyQueryPlan,
    nodes: tuple[OntologyQueryNode, ...],
    outputs: tuple[str, ...] | None = None,
) -> OntologyQueryPlan:
    body = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    if outputs is not None:
        body["output_node_ids"] = list(outputs)
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


def _health() -> tuple[Any, OntologyQueryPlan]:
    utterance = "Is vm-app-01 healthy?"
    admission, compilation = _compile(
        utterance, _form(utterance, operation="lookup", measure="health")
    )
    return admission, compilation.goals[0].batches[0].plan


def test_a_health_lookup_reads_the_reviewed_single_target_assessment() -> None:
    utterance = "Is vm-app-01 healthy?"
    _admission, compilation = _compile(
        utterance, _form(utterance, operation="lookup", measure="health")
    )

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    kinds = [node.kind for node in batch.plan.nodes]
    assert kinds.count(QueryNodeKind.METRIC_SCOPE_SERIES) == 3
    functions = [
        node.arguments["function_name"]
        for node in batch.plan.nodes
        if node.kind is QueryNodeKind.FUNCTION
    ]
    assert functions == [
        "query.resource_current_state",
        "query.resource_change_activity",
        "query.target_health_assessment",
    ]
    assert batch.plan.output_node_ids == ("g1-target-health-assessment",)
    assert batch.frame.output_shape == "target_health_assessment"
    seconds = int(TARGET_HEALTH_WINDOW.total_seconds())
    # The fixed window is stated, so the answer restates it through a reviewed notice.
    assert goal.limitations == (f"time_window_fixed:{seconds}",)
    assert f"window.fixed.{seconds}" in batch.frame.evidence_requirements


def test_a_health_lookup_never_reads_a_stated_window_or_a_missing_reader() -> None:
    utterance = "Was vm-app-01 healthy in the last 2 hours?"
    window = {
        "kind": "window",
        "value": {"duration": {"amount": 2, "unit": "hour"}},
        "cue": span(utterance, "in the last 2 hours"),
    }
    _admission, windowed = _compile(
        utterance, _form(utterance, operation="lookup", measure="health", time=window)
    )
    plain = "Is vm-app-01 healthy?"
    _admission, unbound = _compile(
        plain,
        _form(plain, operation="lookup", measure="health"),
        unbound=("query.target_health_assessment",),
    )

    assert windowed.goals[0].reasons == ("time_unsupported:window",)
    assert unbound.goals[0].reasons == ("function_unavailable:query.target_health_assessment",)


def test_the_verifier_recomputes_every_health_argument() -> None:
    admission, plan = _health()

    def swapped(arguments: dict[str, Any]) -> None:
        arguments["concept_id"] = "resource.memory.usage_pct"

    def widened(arguments: dict[str, Any]) -> None:
        arguments["start"] = (NOW - timedelta(days=7)).isoformat()

    def longer(arguments: dict[str, Any]) -> None:
        arguments["arguments"]["lookback_seconds"] = 86_400

    assert _violations(admission, plan) == ()
    assert "prov_metric_window:g1-health-cpu" in _violations(
        admission, _rewrite(plan, "g1-health-cpu", swapped)
    )
    assert "prov_metric_window:g1-health-cpu" in _violations(
        admission, _rewrite(plan, "g1-health-cpu", widened)
    )
    assert "prov_function_arguments:g1-health-activity" in _violations(
        admission, _rewrite(plan, "g1-health-activity", longer)
    )
    # A plan that answers health from the current state alone is not the assessment.
    kept = tuple(
        node for node in plan.nodes if node.node_id in {"g1-anchor", "g1-health-current-state"}
    )
    current_only = _with_nodes(plan, kept, outputs=("g1-health-current-state",))
    assert "sem_health_read_differs" in _violations(admission, current_only)


def test_a_state_history_reads_every_reviewed_transition_in_the_window() -> None:
    utterance = "What happened to the state of vm-app-01 in the last 6 hours?"
    window = {
        "kind": "window",
        "value": {"duration": {"amount": 6, "unit": "hour"}},
        "cue": span(utterance, "in the last 6 hours"),
    }
    admission, compilation = _compile(
        utterance, _form(utterance, operation="history", measure="state", time=window)
    )

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    read = next(node for node in batch.plan.nodes if node.kind is QueryNodeKind.FUNCTION)
    arguments = read.arguments["arguments"]
    assert read.arguments["function_name"] == "query.resource_state_transitions"
    assert arguments["start_at"] == (NOW - timedelta(hours=6)).isoformat()
    assert arguments["end_at"] == arguments["known_at"] == NOW.isoformat()
    assert batch.frame.output_shape == "resource_state_transitions"
    plan = batch.plan

    def narrowed(values: dict[str, Any]) -> None:
        values["arguments"]["to_states"] = ["running"]

    assert _violations(admission, plan) == ()
    assert f"prov_function_arguments:{read.node_id}" in _violations(
        admission, _rewrite(plan, read.node_id, narrowed)
    )


@pytest.mark.parametrize("measure", ["event", "change"])
def test_a_metric_window_is_never_accepted_outside_a_health_lookup(measure: str) -> None:
    utterance = "What happened to vm-app-01?"
    admission, compilation = _compile(
        utterance, _form(utterance, operation="history", measure=measure)
    )
    plan = compilation.goals[0].batches[0].plan
    _health_admission, health_plan = _health()
    metric = next(
        node for node in health_plan.nodes if node.kind is QueryNodeKind.METRIC_SCOPE_SERIES
    )
    widened = _with_nodes(
        plan, (*plan.nodes, metric.model_copy(update={"depends_on": ("g1-anchor",)}))
    )

    assert f"prov_unexpected_node:{metric.node_id}:metric_scope_series" in _violations(
        admission, widened
    )


def test_the_fixed_window_notice_restates_the_assessment_window() -> None:
    from fdai_core_service.semantic_verified_rows import with_stated_notices

    english = with_stated_notices(
        "## Verified result\n\n- rows", ("window.fixed.1800",), locale="en"
    )
    korean = with_stated_notices("## 검증된 결과\n\n- 행", ("window.fixed.1800",), locale="ko")

    assert (
        "Read window: the last 30 minutes, the reviewed fixed window of the health assessment."
        in english
    )
    assert "- 조회 기간: 상태 이상 평가의 검토된 고정 기간인 최근 30분" in korean


def test_a_compiled_health_lookup_releases_with_its_fixed_window_notice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from tests.conversation.test_semantic_compiled_answers import (
        _completions,
        _observation,
        _ticket,
    )

    caplog.set_level(logging.INFO, logger="fdai.core.conversation.semantic_compiled_answers")

    utterance = "Is vm-app-01 healthy?"
    _admission, compilation = _compile(
        utterance, _form(utterance, operation="lookup", measure="health")
    )

    outcome = _ticket(_observation(compilations=(compilation,))).outcome(
        manifest_digest="d", observations=[]
    )

    assert outcome is not None and outcome.frame is not None
    assert outcome.frame.output_shape == "target_health_assessment"
    assert _completions(caplog) == ["selected"]
