"""Production semantic composition tests for schema-level relationships."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.relationship_queries import (
    ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
)
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_CATALOG_ROOT = Path(__file__).resolve().parents[4] / "rule-catalog"


class _RelationshipModel:
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": ["PythonTask", "VmTaskRun"],
            "measure_concepts": [],
            "temporal_scope": {},
            "output_shape": "ontology_relationships",
            "evidence_requirements": ["ontology_relationship_evidence"],
            "unresolved_terms": [],
            "clarification": None,
            "confidence": 0.95,
        }

    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "relationships",
                    "kind": "function",
                    "depends_on": [],
                    "arguments": {
                        "function_name": ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
                        "arguments": {
                            "object_types": ["PythonTask", "VmTaskRun"],
                            "limit": 100,
                        },
                        "dependency_arguments": {},
                    },
                    "output_kind": "ontology.relationships",
                }
            ],
            "output_node_ids": ["relationships"],
        }


def _object_type(name: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )


@pytest.mark.parametrize(
    "utterance",
    [
        "Why is PythonTask connected to VmTaskRun?",
        "PythonTask가 왜 VmTaskRun과 연결된 거야?",
    ],
)
async def test_runtime_executes_exact_release_relationship_query(utterance: str) -> None:
    python_task = _object_type("PythonTask")
    vm_task_run = _object_type("VmTaskRun")
    executes_task = OntologyLinkType(
        schema_version="1.0.0",
        name="executes_task",
        version="1.0.0",
        from_type="VmTaskRun",
        to_type="PythonTask",
        cardinality=LinkCardinality.MANY_TO_ONE,
        description="The immutable PythonTask artifact selected by a VM task run.",
    )
    functions = operational_function_types(())
    release = build_ontology_release(
        object_types=(python_task, vm_task_run),
        link_types=(executes_task,),
        function_types=functions,
    )
    catalog = OntologyCatalog(
        object_types=(python_task, vm_task_run),
        interface_types=(),
        interface_implementations=(),
        link_types=(executes_task,),
        action_types=(),
        property_semantics=empty_property_semantic_registry(),
    )
    runtime = build_semantic_query_runtime(
        model=_RelationshipModel(),
        ontology_release=release,
        ontology_catalog=catalog,
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(python_task, vm_task_run),
            link_types=(executes_task,),
        ),
    )

    result = await runtime.handle(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert result.execution is not None
    value = result.execution.results["relationships"].value
    assert value["relationships"] == [
        {
            "link_type": "executes_task",
            "from_type": "VmTaskRun",
            "to_type": "PythonTask",
            "cardinality": "many_to_one",
            "description": "The immutable PythonTask artifact selected by a VM task run.",
        }
    ]
    assert value["execution_authority"] is False


def test_semantic_prompts_select_exact_relationship_function() -> None:
    prompts = FileSystemPromptRegistry(_CATALOG_ROOT)
    frame = prompts.get_base("semantic.query.frame")
    plan = prompts.get_base("semantic.query.plan")

    assert "query.ontology_relationships" in frame.body
    assert "do not treat the ObjectType names as runtime object ids" in frame.body
    assert '"function_name":"query.ontology_relationships"' in plan.body
    assert '"object_types"' in plan.body
    assert "never convert objecttype names into object_set root_ids" in plan.body.casefold()
