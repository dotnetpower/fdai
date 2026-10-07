from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from fdai_core_service import development_decisions
from fdai_core_service.development_decisions import (
    bind_decision_events,
    observe_semantic_decision,
    record_decision_observations,
)
from fdai_runtime_diagnostics.decisions import decision_snapshot, reset_decision_traces

_PLANNER = logging.getLogger("fdai.core.conversation.semantic_planning")
_SECRET_TEXT = (
    "컨테이너 앱",
    "rg-fdai-dev-krc",
    "Here are your apps",
    "aks-bori-dev",
    "draft text",
)


@dataclass
class _Observation:
    model: str
    trace_call: dict[str, Any] = field(default_factory=dict)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    monkeypatch.setenv("FDAI_DEVELOPMENT_DIAGNOSTICS", "1")
    caplog.set_level(logging.INFO, logger="fdai")
    reset_decision_traces()
    yield
    reset_decision_traces()


def _call(kind: str, body: dict[str, Any], model: str = "narrator-deployment-a") -> _Observation:
    return _Observation(
        model=model,
        trace_call={
            "kind": kind,
            "status": "completed",
            "duration_ms": 812,
            "response": {"content": json.dumps(body, ensure_ascii=False)},
        },
    )


def _observations() -> list[_Observation]:
    preflight = {
        "social_act": "none",
        "operational_signal": "explicit",
        "context_dependency": "none",
        "knowledge_signal": "none",
        "general_answer": {"answer": "draft text"},
        "operational_family": "resource_collection",
        "operational_window": "none",
        "operational_targets": [
            {
                "kind": "resource_type_filter",
                "value": "컨테이너 앱",
                "source_start": 19,
                "source_end": 25,
            },
            {
                "kind": "resource_group",
                "value": "rg-fdai-dev-krc",
                "source_start": 0,
                "source_end": 15,
            },
        ],
        "operational_facets": ["list"],
        "request_topics": ["resource_inventory"],
        "confidence": 0.96,
    }
    judgment = {
        "primary_intent": "query.contextual_resources",
        "secondary_intents": [],
        "targets": [
            {
                "kind": "resource_group",
                "value": "rg-fdai-dev-krc",
                "canonical_value": "rg-fdai-dev-krc",
                "source_start": 0,
                "source_end": 15,
            }
        ],
        "requested_facets": ["list", "zzqx_unreviewed_word"],
        "confidence": 0.94,
        "ambiguous": False,
        "alternatives": [],
        "unresolved_terms": ["aks-bori-dev"],
        "clarification": None,
        "direct_response": None,
        "discourse_mode": "direct",
        "action_posture": "advise_only",
    }
    return [
        _call("conversation-preflight", preflight),
        _call("semantic-judgment", judgment),
        _call("semantic-concept-selection", {}, model="narrator-deployment-a"),
        _call("semantic-concept-selection", {}, model="narrator-deployment-b"),
    ]


def _semantic_result() -> dict[str, Any]:
    return {
        "session_id": "session-under-test-1",
        "turn_sequence": 4,
        "semantic_route": "verified_query_plan",
        "disposition": "answered",
        "reason_code": "semantic_answer_partial",
        "answer": "Here are your apps: rg-fdai-dev-krc",
        "checks_completed": 3,
        "checks_total": 3,
        "plan_digest": "sha256:" + "a" * 64,
        "intent_graph": {
            "action_posture": "advise_only",
            "clarification": None,
            "confidence": 0.94,
            "goals": [
                {
                    "capability": "query.object_set",
                    "intent": "object_set",
                    "depends_on": [],
                    "arguments": {
                        "definition": {
                            "predicates": [
                                {
                                    "property": "name",
                                    "operator": "equals",
                                    "equals": "rg-fdai-dev-krc",
                                },
                                {
                                    "property": "type",
                                    "operator": "equals",
                                    "equals": "compute.container-app",
                                },
                                {
                                    "property": "type",
                                    "operator": "equals",
                                    "equals": "aks-bori-dev",
                                },
                            ]
                        }
                    },
                }
            ],
        },
        "assurance_observation": {
            "frame": {
                "operation": "select",
                "output_shape": "property_filtered_resources",
                "subject_types": ["Resource"],
                "measure_concepts": ["type"],
                "temporal_scope": "none",
            },
            "capabilities": ["object_set"],
            "object_types": ["Resource"],
            "link_types": [],
            "function_types": [],
            "ontology_paths": [],
            "evidence_posture": "incomplete",
            "read_performed": True,
            "limitation_kinds": [],
        },
    }


def _record_turn() -> None:
    with bind_decision_events() as turn:
        assert turn is not None
        _PLANNER.info("semantic_judgment_proposal_retry", extra={"attempt": 2, "tier": "t1"})
        _PLANNER.info(
            "semantic_planning_judgment_advise_only",
            extra={
                "disposition": "accepted",
                "primary_intent": "query.contextual_resources",
                "requested_facets": "resource_collection,list",
                "target_kinds": "resource_group,resource_type_filter",
                "target_count": 2,
                "canonical_target_types": "compute.container-app,rg-fdai-dev-krc",
            },
        )
        _PLANNER.info(
            "semantic_planning_stage_completed",
            extra={
                "stage": "plan_verify",
                "plan_source": "server_stated_filter",
                "plan_nodes": "object_set[Resource;name equals]",
                "output_shape": "property_filtered_resources",
            },
        )
        _PLANNER.info("semantic_plan_rejected", extra={"validation_reason": "rg-fdai-dev-krc"})
        _PLANNER.warning(
            "semantic_judgment_proposal_rejected",
            extra={"failure_type": "UncoveredConstraintError", "uncovered_roles": ["times"]},
        )
        record_decision_observations(
            _observations(),
            SimpleNamespace(disposition=SimpleNamespace(value="planned"), reason="plan_verified"),
        )
        projection = {"semantic_result": _semantic_result()}
        observe_semantic_decision(projection)
        observe_semantic_decision(projection)


def test_call_metrics_are_numeric_and_never_capture_grounding_content() -> None:
    observations = _observations()
    observations[2].trace_call["usage"] = {
        "prompt_tokens": 123,
        "completion_tokens": 7,
        "total_tokens": 130,
    }
    observations[2].trace_call["response"] = {"content": "private question and answer"}
    with bind_decision_events():
        record_decision_observations(observations)
        observe_semantic_decision({"semantic_result": _semantic_result()})
    trace = decision_snapshot().traces[0]
    calls = [step for step in trace.steps if step.stage == "call.semantic_concept_selection"]
    assert calls[0].attributes["duration_ms"] == 812
    assert calls[0].attributes["prompt_tokens"] == 123
    assert calls[0].attributes["completion_tokens"] == 7
    assert "private question and answer" not in trace.model_dump_json()


def test_call_metrics_keep_cached_prompt_tokens_and_start_offsets() -> None:
    observations = _observations()
    observations[0].trace_call["started_at"] = "2026-10-06T02:30:05.800000+00:00"
    observations[2].trace_call["started_at"] = "2026-10-06T02:30:10.900000+00:00"
    observations[2].trace_call["usage"] = {
        "prompt_tokens": 4197,
        "completion_tokens": 70,
        "total_tokens": 4267,
        "cached_tokens": 3968,
    }
    with bind_decision_events():
        record_decision_observations(observations)
        observe_semantic_decision({"semantic_result": _semantic_result()})
    trace = decision_snapshot().traces[0]
    first = trace.steps[0]
    call = next(step for step in trace.steps if step.stage == "call.semantic_concept_selection")
    assert first.attributes["start_offset_ms"] == 0
    assert call.attributes["start_offset_ms"] == 5100
    assert call.attributes["cached_tokens"] == 3968


def test_a_turn_records_one_content_free_trace_with_step_bound_cues() -> None:
    _record_turn()
    snapshot = decision_snapshot()
    assert len(snapshot.traces) == 1
    trace = snapshot.traces[0]
    encoded = trace.model_dump_json()
    for text in _SECRET_TEXT:
        assert text not in encoded
    assert "narrator-deployment" not in encoded
    assert "session-under-test" not in encoded
    assert trace.session.startswith("s")
    assert trace.turn_sequence == 4
    stages = [step.stage for step in trace.steps]
    assert stages == [
        "preflight",
        "judgment",
        "call.semantic_concept_selection",
        "call.semantic_concept_selection",
        "grounding",
        "event.semantic_judgment_proposal_retry",
        "event.semantic_planning_judgment_advise_only",
        "event.semantic_planning_stage_completed",
        "event.semantic_plan_rejected",
        "event.semantic_judgment_proposal_rejected",
        "intent_graph",
        "outcome",
    ]
    by_stage = {step.stage: step.attributes for step in trace.steps}
    preflight, judgment, grounding = (
        by_stage[stage] for stage in ("preflight", "judgment", "grounding")
    )
    assert preflight["family"] == "resource_collection"
    assert preflight["target_kinds"] == ("resource_type_filter", "resource_group")
    assert preflight["general_answer"] is True
    assert judgment["intent"] == "query.contextual_resources"
    assert judgment["facets"] == ("list", "~")
    assert judgment["unresolved_terms"] == 1
    assert grounding["calls"] == 2
    assert len(set(grounding["models"])) == 2
    assert by_stage["event.semantic_planning_judgment_advise_only"] == {
        "canonical_target_types": ("compute.container-app", "~"),
        "disposition": "accepted",
        "primary_intent": "query.contextual_resources",
        "requested_facets": ("resource_collection", "list"),
        "target_count": 2,
        "target_kinds": ("resource_group", "resource_type_filter"),
    }
    stage_event = by_stage["event.semantic_planning_stage_completed"]
    assert stage_event == {
        "output_shape": "property_filtered_resources",
        "plan_source": "server_stated_filter",
        "stage": "plan_verify",
    }
    assert by_stage["event.semantic_plan_rejected"] == {"validation_reason": "~"}
    assert by_stage["event.semantic_judgment_proposal_rejected"] == {
        "failure_type": "UncoveredConstraintError",
        "uncovered_roles": ("times",),
    }
    graph = by_stage["intent_graph"]
    assert graph["predicates"] == (
        "name:equals",
        "type:equals:compute.container-app",
        "type:equals",
    )
    outcome = trace.steps[-1].attributes
    assert (outcome["planning_disposition"], outcome["planning_reason"]) == (
        "planned",
        "plan_verified",
    )
    cues = {(cue.code, trace.steps[cue.step].stage) for cue in trace.cues}
    assert cues == {
        ("unreviewed_model_token", "judgment"),
        ("judgment_retry", "event.semantic_judgment_proposal_retry"),
        ("plan_rejected", "event.semantic_plan_rejected"),
        ("judgment_rejected", "event.semantic_judgment_proposal_rejected"),
        ("preflight_target_uncovered", "preflight"),
        ("partial_answer", "outcome"),
        ("evidence_incomplete", "outcome"),
    }


def test_events_outside_a_bound_turn_and_disabled_channels_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _PLANNER.info("semantic_judgment_proposal_retry", extra={"attempt": 2})
    observe_semantic_decision({"semantic_result": _semantic_result()})
    monkeypatch.delenv("FDAI_DEVELOPMENT_DIAGNOSTICS")
    with bind_decision_events() as turn:
        assert turn is None
        record_decision_observations(_observations())
        observe_semantic_decision({"semantic_result": _semantic_result()})
    monkeypatch.setenv("FDAI_DEVELOPMENT_DIAGNOSTICS", "1")
    assert decision_snapshot().traces == ()


def test_a_projection_failure_never_reaches_the_product_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("projection defect")

    monkeypatch.setattr(development_decisions, "semantic_decision_steps", broken)
    with bind_decision_events():
        observe_semantic_decision({"semantic_result": _semantic_result()})
    assert decision_snapshot().traces == ()


def test_adaptive_takeover_and_thread_dependency_point_at_the_adaptive_plan() -> None:
    plan = {
        "route": "adaptive",
        "social_act": "none",
        "context_dependency": "active_thread",
        "action_requested": False,
        "goals": [{"goal_id": "g1", "kind": "knowledge", "question": "키 볼트 목록?"}],
        "draft": {"sections": [{"goal_id": "g1", "text": "draft text"}]},
    }
    with bind_decision_events():
        record_decision_observations([_call("adaptive-plan", plan)])
        result = {
            "session_id": "session-2",
            "turn_sequence": 9,
            "semantic_route": "semantic_advisory_response",
            "disposition": "advisory_response",
            "reason_code": "semantic_advisory_response",
            "adaptive_answer": {"quality_status": "verified", "goals": [{}], "refinements": []},
        }
        observe_semantic_decision({"semantic_result": result})
    trace = decision_snapshot().traces[0]
    assert "키 볼트" not in trace.model_dump_json()
    assert trace.steps[0].stage == "adaptive.plan"
    assert trace.steps[0].attributes["goal_kinds"] == ("knowledge",)
    cues = {(cue.code, cue.step) for cue in trace.cues}
    assert {("adaptive_takeover", 0), ("active_thread_dependency", 0)} <= cues
    assert ("advisory_response_outcome", 1) in cues


def test_the_trace_records_the_projection_the_turn_delivers() -> None:
    answered = _semantic_result()
    held = {
        **_semantic_result(),
        "disposition": "held",
        "reason_code": "operational_evidence_over_budget",
        "assurance_observation": None,
        "intent_graph": None,
    }
    with bind_decision_events():
        record_decision_observations(_observations())
        observe_semantic_decision({"semantic_result": answered})
        observe_semantic_decision({"semantic_result": held})
        assert decision_snapshot().traces == ()
    traces = decision_snapshot().traces
    assert len(traces) == 1
    outcome = traces[0].steps[-1].attributes
    assert (outcome["disposition"], outcome["reason_code"]) == (
        "held",
        "operational_evidence_over_budget",
    )
    assert "held_outcome" in {cue.code for cue in traces[0].cues}


def test_the_compiled_answer_event_keeps_closed_reasons_and_points_a_cue_at_it() -> None:
    with bind_decision_events():
        _PLANNER.info(
            "semantic_compiled_answer_completed",
            extra={
                "result": "declined",
                "released": False,
                "review": "uncovered",
                "review_reasons": ["review_uncovered:asks:3-5", "kv-a:quoted"],
                "pass_dispositions": ["admitted"],
                "goal_statuses": ["unsupported"],
                "goal_reasons": ["operation_unsupported:rank", "rg-fdai-dev-krc quoted"],
                "goal_limitations": [],
                "decline_reason": "not_released",
                "batch_count": 0,
                "form_shapes": ["m1:instance:name", "qualifier:m1:m2:containment", "m1 kv-a"],
                "concept_values": ["m2:state:resource_state.deallocated", "m3:region:kv a"],
                "model_calls": 5,
                "elapsed_ms": 4100,
            },
        )
        _PLANNER.info(
            "semantic_compiled_answer_veto",
            extra={
                "plan_source": "server_stated_filter",
                "goal_reasons": ["filter_unsupported:region"],
            },
        )
        observe_semantic_decision({"semantic_result": _semantic_result()})
    trace = decision_snapshot().traces[0]
    step = next(
        item for item in trace.steps if item.stage == "event.semantic_compiled_answer_completed"
    )
    assert step.attributes["goal_reasons"] == ("operation_unsupported:rank", "~")
    # A server code keeps its closed prefix; a span suffix is dropped, never shown.
    assert step.attributes["review_reasons"] == ("review_uncovered:asks", "~")
    assert step.attributes["released"] is False
    assert step.attributes["model_calls"] == 5
    assert step.attributes["decline_reason"] == "not_released"
    assert step.attributes["batch_count"] == 0
    # A form shape keeps closed tokens and redacts anything that is not one.
    assert step.attributes["form_shapes"] == (
        "m1:instance:name",
        "qualifier:m1:m2:containment",
        "~",
    )
    # A bound catalog value is a closed token; anything else keeps only its closed prefix.
    assert step.attributes["concept_values"] == ("m2:state:resource_state.deallocated", "m3:region")
    assert "compiled_answer_veto" in {cue.code for cue in trace.cues}
    assert "rg-fdai-dev-krc" not in trace.model_dump_json()
    assert "compiled_answer_declined" in {cue.code for cue in trace.cues}
