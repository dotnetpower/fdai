"""E11: a stated metric threshold or order over a collection compiles to one metric reader."""

from __future__ import annotations

import json
from typing import Any

from fdai.core.conversation.semantic_reasoning_compiler import (
    GoalStatus,
    compile_question_form,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_verification import verify_goal_semantics

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

_CPU = "resource.cpu.utilization_pct"
_LABELS = ((_CPU, "CPU utilization percentage"),)
_UNITS = ((_CPU, "percent"),)
_RECEIPT = concepts(
    ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
    ("m2", MentionDomain.METRIC, (_CPU,)),
)


def _threshold(
    utterance: str, *, operation: str = "select", unit: str = "percent"
) -> dict[str, Any]:
    comparison: dict[str, Any] = {
        "comparator": "gt",
        "value": "90",
        "value_span": span(utterance, "90"),
        "comparator_span": span(utterance, "above"),
        "unit": unit,
    }
    if unit != "unit_unstated":
        comparison["unit_span"] = span(utterance, "%")
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
            {"id": "m2", "form": "concept", "domain": "metric", "span": span(utterance, "CPU")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "metric", "mention": "m2", "comparison": comparison}],
                "cue": span(utterance, "Which" if operation == "select" else "How many"),
                "confidence": 0.9,
            }
        ],
    }


def _ranked(utterance: str, *, limit: int | None = None) -> dict[str, Any]:
    order: dict[str, Any] = {"direction": "descending", "cue": span(utterance, "highest")}
    if limit is not None:
        order.update(limit=limit, limit_span=span(utterance, str(limit)))
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
            {"id": "m2", "form": "concept", "domain": "metric", "span": span(utterance, "CPU")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "rank",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "metric", "mention": "m2", "order": order},
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }


def _compile(
    utterance: str, form: dict[str, Any], *, units: tuple[tuple[str, str], ...] = _UNITS
) -> Any:
    admission = admitted(form, utterance)
    manifest = production_manifest(metric_labels=_LABELS, metric_units=units)
    compilation = compile_question_form(
        admission,
        concepts=_RECEIPT,
        manifest=manifest,
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )
    return compilation.goals[0], admission, manifest


def _metric_arguments(goal: Any) -> dict[str, Any]:
    (batch,) = goal.batches
    node = next(item for item in batch.plan.nodes if item.kind.value == "function")
    return json.loads(node.arguments_json)["arguments"]


def test_a_threshold_lists_matching_members_and_every_unknown_one() -> None:
    utterance = "Which VMs have CPU above 90%?"
    goal, _admission, _manifest = _compile(utterance, _threshold(utterance))

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert _metric_arguments(goal) == {
        "metric_concepts": [_CPU],
        "window_seconds": _metric_arguments(goal)["window_seconds"],
        "comparator": "gt",
        "threshold": "90",
        "threshold_unit": "percent",
        "list_unknown": True,
    }
    assert goal.batches[0].frame.output_shape == "resource_metric_list"


def test_a_counted_threshold_counts_matches_alone() -> None:
    utterance = "How many VMs have CPU above 90%?"
    goal, _admission, _manifest = _compile(utterance, _threshold(utterance, operation="count"))

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert _metric_arguments(goal)["list_unknown"] is False
    kinds = [node.kind.value for node in goal.batches[0].plan.nodes]
    assert kinds == ["object_set", "function", "aggregate"]


def test_a_rank_reads_the_whole_collection_unless_a_count_is_stated() -> None:
    whole_utterance = "Which VMs have the highest CPU?"
    top_utterance = "Which 3 VMs have the highest CPU?"
    whole, _a, _m = _compile(whole_utterance, _ranked(whole_utterance))
    top, _a, _m = _compile(top_utterance, _ranked(top_utterance, limit=3))

    assert whole.status is GoalStatus.COMPILED, whole.reasons
    assert top.status is GoalStatus.COMPILED, top.reasons
    assert "order_limit" not in _metric_arguments(whole)
    assert _metric_arguments(whole)["order_direction"] == "descending"
    assert _metric_arguments(top)["order_limit"] == 3


def test_a_threshold_in_another_unit_clarifies_and_an_unreviewed_unit_holds() -> None:
    utterance = "Which VMs have CPU above 90%?"
    other, _a, _m = _compile(utterance, _threshold(utterance, unit="ms"))
    unreviewed, _a, _m = _compile(utterance, _threshold(utterance), units=())

    assert other.status is GoalStatus.CLARIFY
    assert other.reasons == ("metric_unit_incompatible",)
    assert unreviewed.status is GoalStatus.UNSUPPORTED
    assert unreviewed.reasons == ("metric_unit_unreviewed",)


def test_verification_rejects_a_dropped_threshold_and_counted_unknown_members() -> None:
    utterance = "How many VMs have CPU above 90%?"
    goal, admission, manifest = _compile(utterance, _threshold(utterance, operation="count"))
    plan = goal.batches[0].plan
    form_goal = admission.form.goals[0]

    def violations(nodes: tuple[Any, ...]) -> tuple[str, ...]:
        return verify_goal_semantics(
            form_goal,
            admission=admission,
            concepts=_RECEIPT,
            descriptors=manifest.descriptors,
            plans=(plan.model_copy(update={"nodes": nodes}),),
            default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
            evaluation_time=NOW,
        )

    collection, metric, count = plan.nodes
    arguments = json.loads(metric.arguments_json)
    widened = metric.model_copy(
        update={
            "arguments_json": json.dumps(
                {**arguments, "arguments": {**arguments["arguments"], "threshold": "50"}},
                sort_keys=True,
                separators=(",", ":"),
            )
        }
    )
    counted = metric.model_copy(
        update={
            "arguments_json": json.dumps(
                {**arguments, "arguments": {**arguments["arguments"], "list_unknown": True}},
                sort_keys=True,
                separators=(",", ":"),
            )
        }
    )

    assert violations(plan.nodes) == ()
    assert any(
        item.startswith("prov_function_arguments")
        for item in violations((collection, widened, count))
    )
    assert "sem_metric_unknown_counted" in violations((collection, counted, count))
