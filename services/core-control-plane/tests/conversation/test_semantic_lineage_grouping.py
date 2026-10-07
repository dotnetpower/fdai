from __future__ import annotations

from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.ontology_platform import ObjectSetService
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.lineage_grouping import count_by_nearest_container
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import LinkCardinality, LinkSemanticTrait, OntologyLinkType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    execute,
    fixture_gateway,
    plan_verifier,
    production_catalog,
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


async def test_per_resource_group_count_executes_lineage_grouping_on_fixture_graph() -> None:
    execution, output_id = await _execute_vm_count(await fixture_gateway())

    assert _counts(execution, output_id) == {
        "container-group:rg-1": 1,
        "container-group:rg-2": 1,
    }


async def test_lineage_count_executes_direct_indirect_and_equal_nearest_roots() -> None:
    gateway = await _lineage_gateway(
        resources=(
            ("rg-a", "rg-a", "resource-group", None),
            ("rg-b", "rg-b", "resource-group", None),
            ("nested", "nested", "network.vnet", None),
            ("vm-direct", "vm-direct", "compute.vm", None),
            ("vm-indirect", "vm-indirect", "compute.vm", None),
            ("vm-peer", "vm-peer", "compute.vm", None),
        ),
        links=(
            ("rg-a", "contains", "vm-direct"),
            ("rg-a", "contains", "nested"),
            ("nested", "contains", "vm-indirect"),
            ("rg-a", "contains", "vm-peer"),
            ("rg-b", "contains", "vm-peer"),
        ),
        contains_cardinality=LinkCardinality.MANY_TO_MANY,
    )

    execution, output_id = await _execute_vm_count(gateway)

    assert _counts(execution, output_id) == {
        "container-group:rg-a": 2,
        "ambiguous_membership": 1,
    }


async def test_lineage_count_executes_zero_members_as_an_empty_result() -> None:
    gateway = await _lineage_gateway(
        resources=(
            ("rg-empty", "rg-empty", "resource-group", None),
            ("sql-only", "sql-only", "sql-database", None),
        ),
        links=(("rg-empty", "contains", "sql-only"),),
    )

    execution, output_id = await _execute_vm_count(gateway)

    assert _counts(execution, output_id) == {}


async def _execute_vm_count(gateway: SecuredObjectSetQueryGateway) -> tuple[object, str]:
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
    execution = await execute(batch.plan, gateway)
    assert execution.status == "completed"
    output = next(node for node in batch.plan.nodes if node.node_id in batch.plan.output_node_ids)
    assert output.arguments["operation"] == "count_by_nearest_container"
    assert output.arguments["container_kind"] == "resource-group"
    traversal = next(
        node for node in batch.plan.nodes if node.kind.value == "relationship_traversal"
    )
    assert traversal.arguments["emit_lineage"] is True
    return execution, output.node_id


def _counts(execution: object, output_id: str) -> dict[str, int]:
    table = execution.results[output_id].value  # type: ignore[attr-defined]
    return {row.row_id: int(row.values["value"]) for row in table.rows}


async def _lineage_gateway(
    *,
    resources: tuple[tuple[str, str, str, str | None], ...],
    links: tuple[tuple[str, str, str], ...],
    contains_cardinality: LinkCardinality = LinkCardinality.ONE_TO_MANY,
) -> SecuredObjectSetQueryGateway:
    catalog = production_catalog()
    resource = next(item for item in catalog.object_types if item.name == "Resource")
    contains = (
        OntologyLinkType(
            schema_version="1.0.0",
            name="contains",
            version="2.1.0",
            from_type="Resource",
            to_type="Resource",
            cardinality=contains_cardinality,
            is_transitive=True,
            forward_role="contains",
            reverse_role="contained_by",
            semantic_traits=(LinkSemanticTrait.CONTAINMENT,),
        ),
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(resource,),
        link_types=contains,
        source_complete=True,
        source_generation="lineage-generation",
    )
    for identity, name, resource_type, parent in resources:
        properties = {"id": identity, "name": name, "type": resource_type}
        if parent is not None:
            properties["parent_id"] = parent
        await store.upsert_object(
            OntologyObjectRecord(id=identity, object_type="Resource", properties=properties)
        )
    for source, link_type, target in links:
        await store.upsert_link(
            OntologyLinkRecord(from_id=source, link_type=link_type, to_id=target)
        )
    service = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(interfaces=(), implementations=(), object_types=(resource,)),
        object_type_names=frozenset({resource.name}),
    )
    return SecuredObjectSetQueryGateway(
        service=service,
        object_types={resource.name: resource},
        ontology_release=build_ontology_release(object_types=(resource,), link_types=contains),
        evaluation_cutoff=lambda: NOW,
        graph_completeness=_complete,
    )


async def _complete() -> bool:
    return True


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


def test_a_cut_input_never_states_an_exact_group_count() -> None:
    rows = (_lineage("vm-a", "rg-a", 1), _lineage("vm-b", "rg-b", 1), _lineage("vm-c", "rg-c", 1))
    complete = QueryTable(rows=rows, complete=True, source_generation="fixture-generation")
    cut = QueryTable(
        rows=rows,
        complete=False,
        truncation_reason="traversal_limit",
        source_generation="fixture-generation",
    )

    assert count_by_nearest_container(complete, limit=2).total_rows == 3
    assert count_by_nearest_container(cut, limit=2).total_rows is None
