"""E12: a relation anchored on every member of a kind relates each anchor with lineage."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_admission import AdmissionDisposition
from fdai.core.conversation.semantic_reasoning_compiler import (
    GoalStatus,
    ReasoningCompilation,
    compile_question_form,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain, SemanticQuestionForm
from fdai_service_contracts.ontology_query import QueryNodeKind
from pydantic import ValidationError

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    execute,
    fixture_gateway,
    names,
    plan_verifier,
    production_manifest,
    span,
    synthetic_anchors,
)

_UTTERANCE = "Which VMs does each resource group contain?"
_RECEIPT = concepts(
    ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
    ("m2", MentionDomain.RESOURCE_TYPE, ("resource-group",)),
)


def _form(utterance: str = _UTTERANCE, **relation: Any) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "resource group"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "relation": {
                    "sense": "containment",
                    "anchor": "m2",
                    "anchor_role": "container",
                    "result_role": "member",
                    "cue": span(utterance, "contain"),
                    "anchor_scope": "collection",
                    **relation,
                },
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }


def _compile(form: dict[str, Any], utterance: str = _UTTERANCE) -> ReasoningCompilation:
    admission = admitted(form, utterance)
    return compile_question_form(
        admission,
        concepts=_RECEIPT,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )


async def test_each_member_of_the_anchor_kind_names_its_related_members() -> None:
    goal = _compile(_form()).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    plan = goal.batches[0].plan
    kinds = [node.kind for node in plan.nodes]
    assert kinds == [QueryNodeKind.OBJECT_SET, QueryNodeKind.RELATIONSHIP_TRAVERSAL]
    assert plan.nodes[1].arguments["emit_lineage"] is True
    assert plan.output_node_ids == ("g1-anchors", "g1-related")

    execution = await execute(plan, await fixture_gateway())

    assert execution.status == "completed"
    assert names(execution, "g1-anchors") == {"rg-app", "rg-app-dev"}
    pairs = {
        (row.values["root_name"], row.values["member_name"])
        for row in execution.results["g1-related"].value.rows
    }
    assert pairs == {("rg-app", "vm-app-01"), ("rg-app-dev", "vm-app-dev-01")}


def test_the_stated_direction_decides_which_end_the_anchor_kind_is() -> None:
    forward = _compile(_form()).goals[0]
    swapped = _compile(_form(anchor_role="member", result_role="container")).goals[0]

    assert forward.status is GoalStatus.COMPILED and swapped.status is GoalStatus.COMPILED
    direction = forward.batches[0].plan.nodes[1].arguments["direction"]
    assert swapped.batches[0].plan.nodes[1].arguments["direction"] != direction


def test_a_collection_anchor_reads_one_hop_of_one_sense_only() -> None:
    with pytest.raises(ValidationError, match="one hop of one sense"):
        SemanticQuestionForm.model_validate(_form(reach="transitive"))


def test_a_count_over_a_collection_anchor_is_not_yet_compiled() -> None:
    form = _form()
    form["goals"][0]["operation"] = "count"

    goal = _compile(form).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("collection_anchor_operation_unsupported:count",)


def test_a_collection_anchor_must_name_a_kind() -> None:
    utterance = "Which VMs does resource group rg-app contain?"
    form = _form(utterance)
    form["mentions"][1] = {
        "id": "m2",
        "form": "name",
        "domain": "instance",
        "span": span(utterance, "rg-app"),
    }

    admission = admitted(form, utterance)

    assert admission.disposition is AdmissionDisposition.INVALID
    assert "collection_anchor_kind_missing:g1" in admission.reasons


def test_verification_rejects_a_traversal_from_another_kind() -> None:
    from fdai.core.conversation.semantic_reasoning_collection_relations import (
        collection_anchor_violations,
    )

    goal = _compile(_form()).goals[0]
    plan = goal.batches[0].plan
    form_goal = admitted(_form(), _UTTERANCE).form.goals[0]

    assert (
        collection_anchor_violations(
            form_goal, (plan,), expected_types=("resource-group",), expected_side=None
        )
        == []
    )
    assert collection_anchor_violations(
        form_goal, (plan,), expected_types=("compute.vm",), expected_side=None
    ) == ["sem_collection_anchor_differs"]
    assert collection_anchor_violations(
        form_goal, (plan,), expected_types=None, expected_side=None
    ) == ["sem_collection_anchor_kind_missing"]
