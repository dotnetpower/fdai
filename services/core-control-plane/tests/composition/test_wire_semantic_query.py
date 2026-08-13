"""Production semantic query composition tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.composition import build_semantic_query_runtime, compose_azure_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    CausalEvidenceJoin,
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    QueryTable,
)
from fdai.core.ontology_platform.catalog_queries import CATALOG_SEARCH_RULES_FUNCTION_NAME
from fdai.core.ontology_platform.network_path import NetworkPathResult, NetworkPathStatus
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.acl import REDACTED_PLACEHOLDER
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
CATALOG_DIGEST = "sha256:" + ("a" * 64)
SCHEMA_DIGEST = "sha256:" + ("c" * 64)
VALIDATION_DIGEST = "sha256:" + ("d" * 64)


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
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=operational_function_types(()),
        ),
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


@pytest.mark.parametrize(
    ("catalog_index", "catalog_digest"),
    (
        (InMemoryCatalogSemanticIndex(), None),
        (None, CATALOG_DIGEST),
    ),
)
def test_runtime_rejects_partial_catalog_search_binding(
    catalog_index: InMemoryCatalogSemanticIndex | None,
    catalog_digest: str | None,
) -> None:
    object_type = _object_type()

    with pytest.raises(
        ValueError,
        match="catalog semantic index and digest MUST be supplied together",
    ):
        build_semantic_query_runtime(
            model=_Model(_definition()),
            ontology_release=build_ontology_release(
                object_types=(object_type,),
                function_types=operational_function_types(()),
            ),
            ontology_catalog=_catalog(object_type),
            ontology_store=InMemoryOntologyInstanceStore(
                object_types=(object_type,),
                link_types=(),
            ),
            catalog_index=catalog_index,
            catalog_digest=catalog_digest,
            now=lambda: NOW,
        )


@pytest.mark.parametrize(
    ("metric_registry", "metric_window_provider"),
    (
        (
            MetricSemanticRegistry.build(
                (
                    MetricSemanticDefinition(
                        concept_id="requests.count",
                        provider_metric="requests",
                        canonical_unit="count",
                        aggregation=MetricAggregation.SUM,
                        description="Request count.",
                    ),
                )
            ),
            None,
        ),
        (None, object()),
    ),
)
def test_runtime_rejects_partial_metric_binding(
    metric_registry: MetricSemanticRegistry | None,
    metric_window_provider: object | None,
) -> None:
    object_type = _object_type()

    with pytest.raises(
        ValueError,
        match="metric semantic registry and window provider MUST be supplied together",
    ):
        build_semantic_query_runtime(
            model=_Model(_definition()),
            ontology_release=build_ontology_release(
                object_types=(object_type,),
                function_types=operational_function_types(()),
            ),
            ontology_catalog=_catalog(object_type),
            ontology_store=InMemoryOntologyInstanceStore(
                object_types=(object_type,),
                link_types=(),
            ),
            metric_registry=metric_registry,
            metric_window_provider=metric_window_provider,  # type: ignore[arg-type]
            now=lambda: NOW,
        )


class _TemporalEvidenceModel(_Model):
    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        start = NOW - timedelta(minutes=5)
        nodes = [
            {
                "node_id": "topology-before",
                "kind": "topology_at",
                "depends_on": [],
                "arguments": {"as_of": start.isoformat(), "known_at": NOW.isoformat()},
                "output_kind": "topology.graph",
            },
            {
                "node_id": "topology-after",
                "kind": "topology_at",
                "depends_on": [],
                "arguments": {"as_of": NOW.isoformat(), "known_at": NOW.isoformat()},
                "output_kind": "topology.graph",
            },
            {
                "node_id": "topology-change",
                "kind": "topology_diff",
                "depends_on": ["topology-before", "topology-after"],
                "arguments": {},
                "output_kind": "topology.diff",
            },
            *(
                {
                    "node_id": node_id,
                    "kind": "metric_series",
                    "depends_on": [],
                    "arguments": {
                        "concept_id": concept_id,
                        "resource_id": "resource-a",
                        "start": start.isoformat(),
                        "end": NOW.isoformat(),
                    },
                    "output_kind": "metric.window",
                }
                for node_id, concept_id in (
                    ("cause", "requests.count"),
                    ("effect", "errors.count"),
                )
            ),
            {
                "node_id": "causal-evidence",
                "kind": "evidence_join",
                "depends_on": ["cause", "effect", "topology-change"],
                "arguments": {
                    "feature_cutoff": NOW.isoformat(),
                    "competing_explanations": ["deployment"],
                },
                "output_kind": "causal.join",
            },
        ]
        return {"nodes": nodes, "output_node_ids": ["causal-evidence"]}


class _EmptyTopologyReader:
    async def read(self, *, as_of: datetime, known_at: datetime) -> tuple[()]:
        assert as_of <= known_at
        return ()


class _IncompleteMetricWindowProvider:
    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=(),
            complete=False,
            missing_reason="provider_gap",
            evidence_refs=(f"metric:{definition.concept_id}",),
        )


def _metric_registry() -> MetricSemanticRegistry:
    return MetricSemanticRegistry.build(
        tuple(
            MetricSemanticDefinition(
                concept_id=concept_id,
                provider_metric=provider_metric,
                canonical_unit="count",
                aggregation=MetricAggregation.SUM,
                description=description,
            )
            for concept_id, provider_metric, description in (
                ("requests.count", "requests", "Request count."),
                ("errors.count", "errors", "Error count."),
            )
        )
    )


async def test_runtime_rejects_unavailable_temporal_evidence_kinds() -> None:
    object_type = _object_type()
    runtime = build_semantic_query_runtime(
        model=_TemporalEvidenceModel(_definition()),
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=operational_function_types(()),
        ),
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="Correlate topology and telemetry.",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "unsupported"
    assert result.reason == "semantic_plan_invalid"
    assert result.execution is None


async def test_runtime_executes_temporal_metric_evidence_provider_set() -> None:
    object_type = _object_type()
    runtime = build_semantic_query_runtime(
        model=_TemporalEvidenceModel(_definition()),
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=operational_function_types(()),
        ),
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        topology_reader=_EmptyTopologyReader(),
        metric_registry=_metric_registry(),
        metric_window_provider=_IncompleteMetricWindowProvider(),
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="Correlate topology and telemetry.",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert result.execution is not None
    causal_evidence = result.execution.results["causal-evidence"].value
    assert isinstance(causal_evidence, CausalEvidenceJoin)
    assert causal_evidence.status.value == "unresolved"
    assert "metric_window_incomplete" in causal_evidence.limitations
    assert causal_evidence.execution_authority is False


class _RuleSearchModel(_Model):
    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "rule-candidates",
                    "kind": "function",
                    "depends_on": [],
                    "arguments": {
                        "function_name": CATALOG_SEARCH_RULES_FUNCTION_NAME,
                        "arguments": {
                            "query": "open network security group",
                            "operation": "discover",
                            "corpus": "active",
                            "limit": 5,
                        },
                        "dependency_arguments": {},
                    },
                    "output_kind": "catalog.rule-candidates",
                }
            ],
            "output_node_ids": ["rule-candidates"],
        }


class _ManifestCaptureModel(_Model):
    def __init__(self, definition: ObjectSetDefinition) -> None:
        super().__init__(definition)
        self.function_names: tuple[str, ...] = ()

    def propose_plan(self, **kwargs: Any) -> dict[str, object]:
        self.function_names = tuple(
            descriptor["name"]
            for descriptor in kwargs["descriptors"]
            if descriptor["kind"] == "function"
        )
        return super().propose_plan(**kwargs)


async def test_runtime_hides_unbound_catalog_search_from_planner() -> None:
    object_type = _object_type()
    model = _ManifestCaptureModel(_definition())
    runtime = build_semantic_query_runtime(
        model=model,
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=operational_function_types(()),
        ),
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="Show resources",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert CATALOG_SEARCH_RULES_FUNCTION_NAME not in model.function_names


async def test_runtime_exposes_bound_catalog_search_to_planner() -> None:
    object_type = _object_type()
    model = _ManifestCaptureModel(_definition())
    runtime = build_semantic_query_runtime(
        model=model,
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=operational_function_types(()),
        ),
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        catalog_index=InMemoryCatalogSemanticIndex(),
        catalog_digest=CATALOG_DIGEST,
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="Show resources",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert CATALOG_SEARCH_RULES_FUNCTION_NAME in model.function_names


async def test_runtime_executes_exact_generation_rule_search_without_authority() -> None:
    object_type = _object_type()
    functions = operational_function_types(())
    release = build_ontology_release(
        object_types=(object_type,),
        function_types=functions,
    )
    index = InMemoryCatalogSemanticIndex()
    documents = (
        CatalogSearchDocument(
            rule_id="network.nsg-open-deny",
            text="deny an open network security group",
            neighbor_ids=("network.nsg",),
        ),
    )
    document_manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=CATALOG_DIGEST,
        semantic_schema_digest=SCHEMA_DIGEST,
        ontology_release_digest=release.digest,
        embedding_space_id="rule-search-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=document_manifest,
    )
    metadata = CatalogGenerationMetadata(
        generation_id="rules-active-1",
        generation_digest=generation_digest,
        corpus="active",
        catalog_digest=CATALOG_DIGEST,
        semantic_schema_digest=SCHEMA_DIGEST,
        ontology_release_digest=release.digest,
        embedding_space_id="rule-search-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=document_manifest,
        validation_receipt_digest=VALIDATION_DIGEST,
    )
    await index.stage_generation(metadata, documents)
    await index.activate_generation(
        metadata.generation_id,
        expected_generation_digest=metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
    )
    runtime = build_semantic_query_runtime(
        model=_RuleSearchModel(_definition()),
        ontology_release=release,
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        catalog_index=index,
        catalog_digest=CATALOG_DIGEST,
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="Find the network security group rule.",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert result.execution is not None
    candidates = result.execution.results["rule-candidates"].value
    assert candidates["authority"] == "candidate_only"
    assert candidates["execution_authority"] is False
    assert candidates["candidates"][0]["rule_ref"] == "network.nsg-open-deny"


class _NetworkModel(_Model):
    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "network-graph",
                    "kind": "object_set",
                    "depends_on": [],
                    "arguments": {"definition": self._definition.model_dump(mode="json")},
                    "output_kind": "query.table",
                },
                {
                    "node_id": "network-path",
                    "kind": "function",
                    "depends_on": ["network-graph"],
                    "arguments": {
                        "function_name": "query.network_path_segments",
                        "arguments": {
                            "source_id": "nic-1",
                            "target_id": "route-1",
                            "max_depth": 2,
                            "max_segments": 4,
                        },
                        "dependency_arguments": {"network-graph": "query_result"},
                    },
                    "output_kind": "network.path",
                },
            ],
            "output_node_ids": ["network-path"],
        }


async def test_runtime_executes_issued_network_function_dependency() -> None:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "properties": PropertyDecl(type=PropertyType.OBJECT),
        },
    )
    link_type = OntologyLinkType(
        schema_version="1.0.0",
        name="routes_to",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    functions = operational_function_types(())
    release = build_ontology_release(
        object_types=(object_type,),
        link_types=(link_type,),
        function_types=functions,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(object_type,),
        link_types=(link_type,),
    )
    for object_id, type_id in (("nic-1", "network.nic"), ("route-1", "network.route")):
        await store.upsert_object(
            OntologyObjectRecord(
                id=object_id,
                object_type="Resource",
                properties={"id": object_id, "type": type_id, "properties": {}},
            )
        )
    state_fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="snapshot-1",
        effective_at=NOW,
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory:routes-to",),
    )
    await store.upsert_link(
        OntologyLinkRecord(
            "routes_to",
            "nic-1",
            "route-1",
            properties={
                LINK_OBSERVATION_METADATA_PROPERTY: LinkObservationMetadata(
                    state_fact=state_fact,
                    verification_method="independent-source",
                    verified=True,
                    verifier_identity="inventory-verifier",
                    verifier_revision="verifier-1",
                    verification_receipt_ref="verification:routes-to",
                ).to_mapping()
            },
        )
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="network-path-verification",
        limit=10,
    )
    runtime = build_semantic_query_runtime(
        model=_NetworkModel(definition),
        ontology_release=release,
        ontology_catalog=OntologyCatalog(
            object_types=(object_type,),
            interface_types=(),
            interface_implementations=(),
            link_types=(link_type,),
            action_types=(),
            function_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=store,
        purpose="network-path-verification",
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="Verify the network path.",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered", (
        result.reason,
        (
            tuple(
                (receipt.goal_id, receipt.status.value, receipt.reason)
                for receipt in result.execution.receipts
            )
            if result.execution is not None
            else None
        ),
    )
    assert result.execution is not None
    path = result.execution.results["network-path"].value
    assert isinstance(path, NetworkPathResult)
    assert path.status is NetworkPathStatus.VERIFIED
    assert path.execution_authority is False
