"""Production semantic query composition tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fdai.composition import build_semantic_query_runtime, compose_azure_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    QueryTable,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.acl import REDACTED_PLACEHOLDER
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


def test_azure_string_mode_reaches_semantic_prerequisite_checks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mode = "".join(("az", "ure"))
    container = SimpleNamespace(
        config=SimpleNamespace(
            llm=SimpleNamespace(mode=mode, resolved_models_path=None),
        )
    )

    composition = compose_azure_semantic_query_runtime(
        container=container,  # type: ignore[arg-type]
        ontology_release=None,
        ontology_store=None,
        identity=None,
        http_client=None,
        endpoint=None,
        endpoint_resolver=None,
        catalog_root=tmp_path,
        owner_loop=None,  # type: ignore[arg-type]
    )

    assert mode == "azure"
    assert composition.unavailable_reason == "semantic_resolved_models_unavailable"


class _Model:
    def __init__(self, definition: ObjectSetDefinition, *, available: bool = True) -> None:
        self._definition = definition
        self._available = available

    def propose_frame(self, **_kwargs: Any) -> dict[str, object] | None:
        if not self._available:
            return None
        return {
            "operation": "select",
            "subject_constraints": ["Resource"],
            "measure_concepts": [],
            "temporal_scope": {},
            "output_shape": "resource_list",
            "evidence_requirements": ["authoritative_ontology"],
            "unresolved_terms": [],
            "clarification": None,
            "confidence": 0.9,
        }

    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "resources",
                    "kind": "object_set",
                    "depends_on": [],
                    "arguments": {"definition": self._definition.model_dump(mode="json")},
                    "output_kind": "query.table",
                }
            ],
            "output_node_ids": ["resources"],
        }


def _object_type() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "label": PropertyDecl(type=PropertyType.STRING),
            "owner_note": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
            ),
        },
    )


def _catalog(object_type: OntologyObjectType) -> OntologyCatalog:
    return OntologyCatalog(
        object_types=(object_type,),
        interface_types=(),
        interface_implementations=(),
        link_types=(),
        action_types=(),
        property_semantics=empty_property_semantic_registry(),
    )


def _definition() -> ObjectSetDefinition:
    return ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )


async def _runtime(*, available: bool = True):  # type: ignore[no-untyped-def]
    object_type = _object_type()
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={
                "id": "resource-a",
                "label": "API",
                "owner_note": "owner-only",
            },
        )
    )
    return build_semantic_query_runtime(
        model=_Model(_definition(), available=available),
        ontology_release=build_ontology_release(object_types=(object_type,)),
        ontology_catalog=_catalog(object_type),
        ontology_store=store,
        now=lambda: NOW,
    )


async def test_runtime_binds_exact_request_role_and_returns_evidence() -> None:
    runtime = await _runtime()

    reader_result = await runtime.handle(
        utterance="Show resources",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )
    owner_result = await runtime.handle(
        utterance="Show resources",
        prior_turns=(),
        principal=Principal(id="owner", role=Role.OWNER),
    )

    assert reader_result.disposition == "answered"
    assert owner_result.disposition == "answered"
    assert reader_result.execution is not None
    assert owner_result.execution is not None
    reader_table = reader_result.execution.results["resources"].value
    owner_table = owner_result.execution.results["resources"].value
    assert isinstance(reader_table, QueryTable)
    assert isinstance(owner_table, QueryTable)
    assert reader_table.rows[0].values["properties"]["owner_note"] == REDACTED_PLACEHOLDER
    assert owner_table.rows[0].values["properties"]["owner_note"] == "owner-only"
    assert reader_result.intent_graph_evidence is not None
    evidence_refs = reader_result.intent_graph_evidence["goals"][0]["evidence_refs"]
    assert any(item.startswith("ontology-object-set:") for item in evidence_refs)


async def test_runtime_returns_typed_hold_when_model_provider_is_unavailable() -> None:
    runtime = await _runtime(available=False)

    result = await runtime.handle(
        utterance="Show resources",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "held"
    assert result.reason == "semantic_frame_unavailable"
    assert result.execution is None
