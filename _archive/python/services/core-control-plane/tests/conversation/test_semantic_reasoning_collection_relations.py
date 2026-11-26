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


def test_a_scope_on_a_collection_anchor_is_never_dropped() -> None:
    utterance = "Which VMs does each resource group in rg-app contain?"
    form = _form(utterance)
    form["mentions"].append(
        {"id": "m3", "form": "name", "domain": "instance", "span": span(utterance, "rg-app")}
    )
    form["goals"][0]["filters"] = [{"role": "scope", "mention": "m3"}]
    admission = admitted(form, utterance)

    goal = compile_question_form(
        admission,
        concepts=_RECEIPT,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    ).goals[0]

    assert goal.status is not GoalStatus.COMPILED


def test_verification_requires_the_relation_output_and_an_unnarrowed_anchor_set() -> None:
    from fdai.core.conversation.semantic_reasoning_collection_relations import (
        collection_anchor_violations,
    )
    from fdai_service_contracts.ontology_query import OntologyQueryNode, canonical_json

    plan = _compile(_form()).goals[0].batches[0].plan
    form_goal = admitted(_form(), _UTTERANCE).form.goals[0]
    anchors_only = plan.model_copy(update={"output_node_ids": ("g1-anchors",)})
    definition = dict(plan.nodes[0].arguments["definition"])
    definition["predicates"] = [
        *definition["predicates"],
        {"property": "type", "operator": "equals", "equals": "compute.vm"},
    ]
    narrowed_node = OntologyQueryNode(
        node_id=plan.nodes[0].node_id,
        kind=plan.nodes[0].kind,
        arguments_json=canonical_json({"definition": definition}),
        output_kind=plan.nodes[0].output_kind,
    )
    narrowed = plan.model_copy(update={"nodes": (narrowed_node, *plan.nodes[1:])})

    check = {"expected_types": ("resource-group",), "expected_side": None}
    assert "sem_collection_relation_unlisted" in collection_anchor_violations(
        form_goal, (anchors_only,), **check
    )
    assert "sem_collection_anchor_differs" in collection_anchor_violations(
        form_goal, (narrowed,), **check
    )


def test_a_collection_relation_is_never_read_as_one_flat_list() -> None:
    from fdai.core.conversation.semantic_reasoning_shape import reads_beyond_list

    assert reads_beyond_list(admitted(_form(), _UTTERANCE).form) is True


async def test_lineage_from_many_roots_reads_in_batches_with_the_same_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.core.ontology_platform import query_source_handlers

    plan = _compile(_form()).goals[0].batches[0].plan
    whole = await execute(plan, await fixture_gateway())
    monkeypatch.setattr(query_source_handlers, "LINEAGE_ROOT_BATCH", 1)
    batched = await execute(plan, await fixture_gateway())

    assert batched.status == "completed"
    table = batched.results["g1-related"].value
    assert table.complete is True
    assert {row.row_id for row in table.rows} == {
        row.row_id for row in whole.results["g1-related"].value.rows
    }
    assert any(
        ref.startswith("ontology-object-set-batch:")
        for ref in batched.results["g1-related"].evidence_refs
    )


async def test_a_lineage_walk_beyond_its_read_budget_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.core.ontology_platform import query_source_handlers

    plan = _compile(_form()).goals[0].batches[0].plan
    monkeypatch.setattr(query_source_handlers, "LINEAGE_ROOT_BATCH", 1)
    monkeypatch.setattr(query_source_handlers, "LINEAGE_READ_BUDGET", 1)

    execution = await execute(plan, await fixture_gateway())

    table = execution.results["g1-related"].value
    assert table.complete is False
    assert table.truncation_reason == "lineage_read_budget"


def test_a_sense_of_several_sides_reads_each_side_with_attributable_pairs() -> None:
    utterance = "Which VM is each network interface attached to?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VM"),
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "network interface"),
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
                    "sense": "attachment",
                    "anchor": "m2",
                    "anchor_role": "attached",
                    "result_role": "host",
                    "cue": span(utterance, "attached to"),
                    "anchor_scope": "collection",
                },
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }
    admission = admitted(form, utterance)
    goal = compile_question_form(
        admission,
        concepts=concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.RESOURCE_TYPE, ("network.interface",)),
        ),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    ).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    plan = goal.batches[0].plan
    sides = {
        node.arguments["link_types"][0]
        for node in plan.nodes
        if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL
    }
    assert sides == {"attached_to", "kubernetes_scheduled_on"}
    assert set(plan.output_node_ids) == {node.node_id for node in plan.nodes}


async def test_an_anchor_without_related_members_is_verified_empty_only_when_read_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.core.ontology_platform import query_source_handlers

    # The anchor kind grounds to clusters here, which contain no VM in the fixture graph.
    utterance = _UTTERANCE
    admission = admitted(_form(), utterance)
    plan = (
        compile_question_form(
            admission,
            concepts=concepts(
                ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
                ("m2", MentionDomain.RESOURCE_TYPE, ("kubernetes-cluster",)),
            ),
            manifest=production_manifest(),
            verifier=plan_verifier(),
            purpose=PURPOSE,
            evaluation_time=NOW,
            default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
            utterance=utterance,
            anchors=synthetic_anchors(admission),
        )
        .goals[0]
        .batches[0]
        .plan
    )
    assert plan.nodes[1].arguments["emit_coverage"] is True

    whole = (await execute(plan, await fixture_gateway())).results["g1-related"].value
    coverage = {row.values["root_name"]: row.values["coverage"] for row in whole.rows}
    assert coverage == {"aks-prod-01": "verified_empty"}

    groups = _compile(_form()).goals[0].batches[0].plan
    monkeypatch.setattr(query_source_handlers, "LINEAGE_ROOT_BATCH", 1)
    monkeypatch.setattr(query_source_handlers, "LINEAGE_READ_BUDGET", 1)
    unread = (await execute(groups, await fixture_gateway())).results["g1-related"].value
    assert unread.complete is False
    assert [
        (row.values["root_name"], row.values["coverage"])
        for row in unread.rows
        if "coverage" in row.values
    ] == [("rg-app-dev", "unknown_incomplete")]


def test_verification_requires_coverage_rows_for_a_collection_anchor() -> None:
    from fdai.core.conversation.semantic_reasoning_collection_relations import (
        collection_anchor_violations,
    )
    from fdai_service_contracts.ontology_query import OntologyQueryNode, canonical_json

    plan = _compile(_form()).goals[0].batches[0].plan
    traversal = plan.nodes[1]
    arguments = {key: value for key, value in traversal.arguments.items() if key != "emit_coverage"}
    stripped = OntologyQueryNode(
        node_id=traversal.node_id,
        kind=traversal.kind,
        depends_on=traversal.depends_on,
        arguments_json=canonical_json(arguments),
        output_kind=traversal.output_kind,
    )
    plan = plan.model_copy(update={"nodes": (plan.nodes[0], stripped)})
    form_goal = admitted(_form(), _UTTERANCE).form.goals[0]

    assert "sem_collection_anchor_lineage_missing" in collection_anchor_violations(
        form_goal, (plan,), expected_types=("resource-group",), expected_side=None
    )
