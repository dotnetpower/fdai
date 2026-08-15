"""Production semantic composition tests for schema inventory queries."""

from __future__ import annotations

from typing import Any

from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import QueryTable
from fdai.core.ontology_platform.manifest_queries import ONTOLOGY_MANIFEST_FUNCTION_NAME
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


class _ManifestModel:
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": ["object"],
            "measure_concepts": [],
            "temporal_scope": {},
            "output_shape": "ontology_manifest",
            "evidence_requirements": ["principal_manifest_evidence"],
            "unresolved_terms": [],
            "clarification": None,
            "confidence": 0.95,
        }

    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "manifest",
                    "kind": "function",
                    "depends_on": [],
                    "arguments": {
                        "function_name": ONTOLOGY_MANIFEST_FUNCTION_NAME,
                        "arguments": {"kinds": ["object"], "limit": 1000},
                        "dependency_arguments": {},
                    },
                    "output_kind": "query.table",
                }
            ],
            "output_node_ids": ["manifest"],
        }


async def test_runtime_executes_principal_manifest_query() -> None:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    functions = operational_function_types(())
    release = build_ontology_release(object_types=(resource,), function_types=functions)
    catalog = OntologyCatalog(
        object_types=(resource,),
        interface_types=(),
        interface_implementations=(),
        link_types=(),
        action_types=(),
        property_semantics=empty_property_semantic_registry(),
    )
    runtime = build_semantic_query_runtime(
        model=_ManifestModel(),
        ontology_release=release,
        ontology_catalog=catalog,
        ontology_store=InMemoryOntologyInstanceStore(object_types=(resource,), link_types=()),
    )

    result = await runtime.handle(
        utterance="Which ontology object types are available?",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert result.execution is not None
    table = result.execution.results["manifest"].value
    assert isinstance(table, QueryTable)
    assert table.complete is True
    assert [row.values["name"] for row in table.rows] == ["Resource"]
    assert table.rows[0].values["execution_authority"] is False
