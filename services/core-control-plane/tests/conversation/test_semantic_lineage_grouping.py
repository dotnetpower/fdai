from __future__ import annotations

from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.ontology_platform.lineage_grouping import count_by_nearest_container
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable

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


def test_lineage_grouping_counts_direct_indirect_and_equal_nearest_roots() -> None:
    table = QueryTable(
        rows=(
            _lineage("vm-direct", "rg-a", 1),
            _lineage("vm-indirect", "rg-a", 3),
            _lineage("vm-peer", "rg-a", 2),
            _lineage("vm-peer", "rg-b", 2),
            _lineage("vm-b", "rg-b", 1),
            _lineage("vm-far", "rg-a", 3),
            _lineage("vm-far", "rg-b", 1),
        ),
        complete=True,
        source_generation="fixture-generation",
    )

    grouped = count_by_nearest_container(table, limit=20)

    assert {row.row_id: row.values["value"] for row in grouped.rows} == {
        "container-group:rg-a": 2,
        "container-group:rg-b": 2,
        "ambiguous_membership": 1,
    }
    assert sum(int(row.values["value"]) for row in grouped.rows) == 5
    assert grouped.complete is True
    assert grouped.source_generation == "fixture-generation"


def test_per_resource_group_count_compiles_to_lineage_grouping() -> None:
    utterance = "How many VMs per resource group?"
    form = {
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
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {
                    "kind": "count",
                    "group_by": "container",
                    "mention": "m2",
                    "cue": span(utterance, "per resource group"),
                },
                "cue": span(utterance, "How many"),
                "confidence": 0.91,
            }
        ],
    }
    admission = admitted(form, utterance)
    compilation = compile_question_form(
        admission,
        concepts=concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.RESOURCE_TYPE, ("resource-group",)),
        ),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )
    goal = compilation.goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    output = next(node for node in batch.plan.nodes if node.node_id in batch.plan.output_node_ids)
    assert output.arguments["operation"] == "count_by_nearest_container"
    assert output.arguments["container_kind"] == "resource-group"


def _lineage(member: str, root: str, depth: int) -> QueryRow:
    return QueryRow.from_values(
        f"{member}:{root}:{depth}",
        {
            "member_id": member,
            "root_id": root,
            "depth": depth,
            "path_evidence": f'["{root}","{member}"]',
            "source_generation": "fixture-generation",
        },
    )


def test_a_container_kind_with_no_members_counts_zero_groups_instead_of_failing() -> None:
    from fdai.core.ontology_platform.lineage_grouping import count_by_nearest_container
    from fdai.core.ontology_platform.query_values import QueryTable

    grouped = count_by_nearest_container(
        QueryTable(rows=(), complete=True, source_generation="generation-1"), limit=10
    )

    assert grouped.rows == () and grouped.complete is True
    assert grouped.source_generation == "generation-1"
