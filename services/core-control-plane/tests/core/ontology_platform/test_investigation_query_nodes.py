"""Dependency-wave query nodes used by semantic investigations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    CausalJoinStatus,
    EvidenceJoinNodeHandler,
    MetricComparisonNodeHandler,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
    MetricWindowComparison,
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    OntologyQueryPlanVerifier,
    QueryNodeHeldError,
    QueryNodeResult,
    QueryRow,
    QueryTable,
    SecuredOntologyInstancePathNodeHandler,
    SecuredRelationshipTraversalNodeHandler,
    SecuredTypedPathNodeHandler,
    TopologyDiff,
    build_query_manifest,
    compile_interfaces,
)
from fdai.core.ontology_platform.metric_semantics import MetricAggregation
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.relationship_queries import (
    ontology_relationships_function_type,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing.ontology_instance import InMemoryOntologyInstanceStore
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

NOW = datetime(2026, 8, 20, 3, 0, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


def _catalog() -> tuple[
    OntologyObjectType,
    OntologyObjectType,
    OntologyLinkType,
]:
    service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    dependency = OntologyLinkType(
        schema_version="1.0.0",
        name="service_depends_on_resource",
        version="1.0.0",
        from_type="BusinessService",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    return service, resource, dependency


def _node(
    node_id: str,
    kind: QueryNodeKind,
    *,
    dependencies: tuple[str, ...] = (),
    arguments: dict[str, object] | None = None,
    output_kind: str = "query.table",
) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id=node_id,
        kind=kind,
        depends_on=dependencies,
        arguments_json=canonical_json(arguments or {}),
        output_kind=output_kind,
    )


def _plan(nodes: tuple[OntologyQueryNode, ...], *, manifest: object) -> OntologyQueryPlan:
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": DIGEST,
        "purpose": "operations-review",
        "caller_role": "reader",
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": (nodes[-1].node_id,),
        "execution_authority": False,
    }
    return OntologyQueryPlan(**body, plan_digest=content_digest(body))


def _resolution_node() -> OntologyQueryNode:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(
            kind=ObjectSelectorKind.OBJECT_TYPE,
            name="BusinessService",
        ),
        predicates=(
            ObjectPredicate(
                property="name",
                operator=ObjectPredicateOperator.CONTAINS,
                equals="A service",
            ),
        ),
        as_of=NOW,
        purpose="operations-review",
        limit=2,
    )
    return _node(
        "resolve-target",
        QueryNodeKind.OBJECT_SET,
        arguments={"definition": definition.model_dump(mode="json")},
    )


def _traversal_node(*, direction: str = "outgoing") -> OntologyQueryNode:
    return _node(
        "expand-dependencies",
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        dependencies=("resolve-target",),
        arguments={
            "selector": {"kind": "object_type", "name": "Resource"},
            "link_types": ["service_depends_on_resource"],
            "direction": direction,
            "max_depth": 1,
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )


def test_verifier_accepts_dependency_bound_relationship_traversal() -> None:
    service, resource, dependency = _catalog()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, resource),
        link_types=(dependency,),
    )
    plan = _plan((_resolution_node(), _traversal_node()), manifest=manifest)

    verified = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        )
    ).verify(plan, manifest=manifest)

    assert verified is plan


def test_verifier_rejects_relationship_endpoint_direction_drift() -> None:
    service, resource, dependency = _catalog()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, resource),
        link_types=(dependency,),
    )
    plan = _plan(
        (_resolution_node(), _traversal_node(direction="incoming")),
        manifest=manifest,
    )

    with pytest.raises(ValueError, match="source endpoint type does not match"):
        OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            )
        ).verify(plan, manifest=manifest)


def test_verifier_accepts_an_ordered_typed_path() -> None:
    service, resource, dependency = _catalog()
    workload = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    implemented_by = OntologyLinkType(
        schema_version="1.0.0",
        name="implemented_by",
        version="1.0.0",
        from_type="BusinessService",
        to_type="Workload",
        cardinality=LinkCardinality.ONE_TO_MANY,
    )
    runs_on = OntologyLinkType(
        schema_version="1.0.0",
        name="runs_on",
        version="1.0.0",
        from_type="Workload",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    release = build_ontology_release(
        object_types=(service, workload, resource),
        link_types=(implemented_by, runs_on),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, workload, resource),
        link_types=(implemented_by, runs_on),
    )
    path = _node(
        "typed-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-target",),
        arguments={
            "steps": [
                {
                    "link_type": "implemented_by",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Workload"},
                },
                {
                    "link_type": "runs_on",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                },
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    plan = _plan((_resolution_node(), path), manifest=manifest)

    verified = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.TYPED_PATH)
    ).verify(plan, manifest=manifest)

    assert verified is plan


def test_verifier_accepts_instance_path_with_exact_schema_dependencies() -> None:
    service, resource, dependency = _catalog()
    relationship_function = ontology_relationships_function_type()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
        function_types=(relationship_function,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, resource),
        link_types=(dependency,),
        functions=(relationship_function,),
        bound_function_names=(relationship_function.name,),
    )
    schema = _node(
        "schema",
        QueryNodeKind.FUNCTION,
        arguments={
            "function_name": relationship_function.name,
            "arguments": {
                "object_types": ["BusinessService", "Resource"],
                "limit": 100,
            },
            "dependency_arguments": {},
        },
        output_kind="ontology.relationships",
    )
    path = _node(
        "instance-path",
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
        dependencies=("schema",),
        arguments={
            "root_selector": {"kind": "object_type", "name": "BusinessService"},
            "steps": [
                {
                    "link_type": dependency.name,
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                }
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 50,
        },
    )
    plan = _plan((schema, path), manifest=manifest)

    verified = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.FUNCTION, QueryNodeKind.ONTOLOGY_INSTANCE_PATH)
    ).verify(plan, manifest=manifest)

    assert verified is plan


def test_verifier_rejects_typed_path_endpoint_drift() -> None:
    service, resource, dependency = _catalog()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, resource),
        link_types=(dependency,),
    )
    path = _node(
        "typed-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-target",),
        arguments={
            "steps": [
                {
                    "link_type": "service_depends_on_resource",
                    "direction": "incoming",
                    "selector": {"kind": "object_type", "name": "Resource"},
                }
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    plan = _plan((_resolution_node(), path), manifest=manifest)

    with pytest.raises(ValueError, match="source endpoint type does not match"):
        OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.TYPED_PATH)
        ).verify(plan, manifest=manifest)


def test_verifier_rejects_repetition_for_a_nontransitive_link() -> None:
    service, resource, dependency = _catalog()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, resource),
        link_types=(dependency,),
    )
    path = _node(
        "typed-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-target",),
        arguments={
            "steps": [
                {
                    "link_type": "service_depends_on_resource",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                    "max_hops": 2,
                }
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    plan = _plan((_resolution_node(), path), manifest=manifest)

    with pytest.raises(ValueError, match="transitive self-composable"):
        OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.TYPED_PATH)
        ).verify(plan, manifest=manifest)


async def test_secured_traversal_uses_the_exact_resolved_entity_root() -> None:
    service, resource, dependency = _catalog()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="service:a",
            object_type="BusinessService",
            properties={"id": "service:a", "name": "A service"},
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource:db",
            object_type="Resource",
            properties={"id": "resource:db"},
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(
            link_type="service_depends_on_resource",
            from_id="service:a",
            to_id="resource:db",
        )
    )
    object_sets = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(
            interfaces=(),
            implementations=(),
            object_types=(service, resource),
            release=release,
        ),
        object_type_names=frozenset({"BusinessService", "Resource"}),
    )
    gateway = SecuredObjectSetQueryGateway(
        service=object_sets,
        object_types={"BusinessService": service, "Resource": resource},
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    handler = SecuredRelationshipTraversalNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    roots = QueryTable(
        rows=(QueryRow.from_values("service:a", {"id": "service:a"}),),
        complete=True,
    )

    result = await handler(
        _traversal_node(),
        {"resolve-target": QueryNodeResult(value=roots, evidence_refs=("entity:a",))},
    )

    assert isinstance(result.value, QueryTable)
    assert tuple(row.row_id for row in result.value.rows) == ("resource:db",)
    assert result.evidence_refs[0] == "entity:a"


async def test_secured_traversal_holds_ambiguous_entity_resolution() -> None:
    class _UnusedGateway:
        async def materialize(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("ambiguous roots MUST stop before graph I/O")

    handler = SecuredRelationshipTraversalNodeHandler(
        _UnusedGateway(),  # type: ignore[arg-type]
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    roots = QueryTable(
        rows=(
            QueryRow.from_values("service:a", {"id": "service:a"}),
            QueryRow.from_values("service:b", {"id": "service:b"}),
        ),
        complete=True,
    )

    with pytest.raises(QueryNodeHeldError, match="entity_resolution_ambiguous"):
        await handler(
            _traversal_node(),
            {"resolve-target": QueryNodeResult(value=roots)},
        )


async def test_secured_typed_path_executes_each_link_in_order() -> None:
    service, resource, _dependency = _catalog()
    workload = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    implemented_by = OntologyLinkType(
        schema_version="1.0.0",
        name="implemented_by",
        version="1.0.0",
        from_type="BusinessService",
        to_type="Workload",
        cardinality=LinkCardinality.ONE_TO_MANY,
    )
    runs_on = OntologyLinkType(
        schema_version="1.0.0",
        name="runs_on",
        version="1.0.0",
        from_type="Workload",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    release = build_ontology_release(
        object_types=(service, workload, resource),
        link_types=(implemented_by, runs_on),
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(service, workload, resource),
        link_types=(implemented_by, runs_on),
    )
    for record in (
        OntologyObjectRecord(
            id="service:a",
            object_type="BusinessService",
            properties={"id": "service:a", "name": "A service"},
        ),
        OntologyObjectRecord(
            id="workload:a",
            object_type="Workload",
            properties={"id": "workload:a"},
        ),
        OntologyObjectRecord(
            id="resource:vm",
            object_type="Resource",
            properties={"id": "resource:vm"},
        ),
    ):
        await store.upsert_object(record)
    await store.upsert_link(OntologyLinkRecord("implemented_by", "service:a", "workload:a"))
    await store.upsert_link(OntologyLinkRecord("runs_on", "workload:a", "resource:vm"))
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=(service, workload, resource),
                release=release,
            ),
            object_type_names=frozenset({"BusinessService", "Workload", "Resource"}),
        ),
        object_types={
            "BusinessService": service,
            "Workload": workload,
            "Resource": resource,
        },
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    handler = SecuredTypedPathNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    node = _node(
        "typed-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-target",),
        arguments={
            "steps": [
                {
                    "link_type": "implemented_by",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Workload"},
                },
                {
                    "link_type": "runs_on",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                },
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    roots = QueryTable(
        rows=(QueryRow.from_values("service:a", {"id": "service:a"}),),
        complete=True,
    )

    result = await handler(
        node,
        {"resolve-target": QueryNodeResult(value=roots, evidence_refs=("entity:a",))},
    )

    assert isinstance(result.value, QueryTable)
    assert tuple(row.row_id for row in result.value.rows) == ("resource:vm",)
    assert result.evidence_refs[0] == "entity:a"
    assert len(result.evidence_refs) == 5


async def test_secured_instance_path_preserves_multi_root_service_ownership_lineage() -> None:
    service, resource, _dependency = _catalog()
    workload = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    agent = OntologyObjectType(
        schema_version="1.0.0",
        name="Agent",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    links = (
        OntologyLinkType(
            schema_version="1.0.0",
            name="implemented_by",
            version="1.0.0",
            from_type="BusinessService",
            to_type="Workload",
            cardinality=LinkCardinality.ONE_TO_MANY,
        ),
        OntologyLinkType(
            schema_version="1.0.0",
            name="workload_runs_on",
            version="1.0.0",
            from_type="Workload",
            to_type="Resource",
            cardinality=LinkCardinality.MANY_TO_MANY,
        ),
        OntologyLinkType(
            schema_version="1.0.0",
            name="owns",
            version="1.0.0",
            from_type="Agent",
            to_type="Resource",
            cardinality=LinkCardinality.MANY_TO_MANY,
        ),
    )
    object_types = (service, workload, resource, agent)
    release = build_ontology_release(object_types=object_types, link_types=links)
    store = InMemoryOntologyInstanceStore(
        object_types=object_types,
        link_types=links,
        source_generation="generation-1",
    )
    for prefix in ("a", "b"):
        for record in (
            OntologyObjectRecord(
                id=f"service:{prefix}",
                object_type="BusinessService",
                properties={"id": f"service:{prefix}", "name": f"Service {prefix}"},
            ),
            OntologyObjectRecord(
                id=f"workload:{prefix}",
                object_type="Workload",
                properties={"id": f"workload:{prefix}"},
            ),
            OntologyObjectRecord(
                id=f"resource:{prefix}",
                object_type="Resource",
                properties={"id": f"resource:{prefix}"},
            ),
            OntologyObjectRecord(
                id=f"agent:{prefix}",
                object_type="Agent",
                properties={"id": f"agent:{prefix}"},
            ),
        ):
            await store.upsert_object(record)
        await store.upsert_link(
            OntologyLinkRecord("implemented_by", f"service:{prefix}", f"workload:{prefix}")
        )
        await store.upsert_link(
            OntologyLinkRecord("workload_runs_on", f"workload:{prefix}", f"resource:{prefix}")
        )
        await store.upsert_link(OntologyLinkRecord("owns", f"agent:{prefix}", f"resource:{prefix}"))
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=object_types,
                release=release,
            ),
            object_type_names=frozenset(item.name for item in object_types),
        ),
        object_types={item.name: item for item in object_types},
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    handler = SecuredOntologyInstancePathNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
    )
    schema_values = (
        ("BusinessService", "implemented_by", "Workload"),
        ("Workload", "workload_runs_on", "Resource"),
        ("Agent", "owns", "Resource"),
    )
    dependencies = {
        f"schema-{index}": QueryNodeResult(
            value={
                "object_types": [source, target],
                "relationships": [
                    {
                        "link_type": link_type,
                        "from_type": source,
                        "to_type": target,
                    }
                ],
                "complete": True,
                "authority": "ontology_release",
                "ontology_release_digest": release.digest,
                "execution_authority": False,
            },
            evidence_refs=(f"schema:{index}",),
            authority=EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
        )
        for index, (source, link_type, target) in enumerate(schema_values, start=1)
    }
    node = _node(
        "service-agent-paths",
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
        dependencies=("schema-1", "schema-2", "schema-3"),
        arguments={
            "root_selector": {"kind": "object_type", "name": "BusinessService"},
            "steps": [
                {
                    "link_type": "implemented_by",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Workload"},
                },
                {
                    "link_type": "workload_runs_on",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                },
                {
                    "link_type": "owns",
                    "direction": "incoming",
                    "selector": {"kind": "object_type", "name": "Agent"},
                },
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 50,
        },
    )

    result = await handler(node, dependencies)

    assert result.authority is EvidenceAuthority.SERVER_ONTOLOGY_INSTANCE_PATH
    assert result.authority_inputs == (
        EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
    )
    assert isinstance(result.value, QueryTable)
    assert [
        (
            row.values["root_id"],
            row.values["step_1_id"],
            row.values["step_2_id"],
            row.values["step_3_id"],
        )
        for row in result.value.rows
    ] == [
        ("service:a", "workload:a", "resource:a", "agent:a"),
        ("service:b", "workload:b", "resource:b", "agent:b"),
    ]
    assert any(ref.startswith("ontology-instance-path:") for ref in result.evidence_refs)


async def test_secured_typed_path_does_not_return_an_unreached_same_type_root() -> None:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    routes_to = OntologyLinkType(
        schema_version="1.0.0",
        name="routes_to",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    release = build_ontology_release(object_types=(resource,), link_types=(routes_to,))
    store = InMemoryOntologyInstanceStore(object_types=(resource,), link_types=(routes_to,))
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource:a",
            object_type="Resource",
            properties={"id": "resource:a"},
        )
    )
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=(resource,),
                release=release,
            ),
            object_type_names=frozenset({"Resource"}),
        ),
        object_types={"Resource": resource},
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    handler = SecuredTypedPathNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    node = _node(
        "typed-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-target",),
        arguments={
            "steps": [
                {
                    "link_type": "routes_to",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                }
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    roots = QueryTable(
        rows=(
            QueryRow.from_values(
                "resource:a",
                {"id": "resource:a", "object_type": "Resource"},
            ),
        ),
        complete=True,
    )

    result = await handler(node, {"resolve-target": QueryNodeResult(value=roots)})

    assert isinstance(result.value, QueryTable)
    assert result.value.rows == ()
    assert result.value.complete is True


async def test_secured_typed_path_returns_bounded_transitive_closure() -> None:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    contains = OntologyLinkType(
        schema_version="1.0.0",
        name="contains",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.ONE_TO_MANY,
        is_transitive=True,
    )
    release = build_ontology_release(object_types=(resource,), link_types=(contains,))
    store = InMemoryOntologyInstanceStore(object_types=(resource,), link_types=(contains,))
    for identifier in ("resource:a", "resource:b", "resource:c"):
        await store.upsert_object(OntologyObjectRecord(identifier, "Resource", {"id": identifier}))
    await store.upsert_link(OntologyLinkRecord("contains", "resource:a", "resource:b"))
    await store.upsert_link(OntologyLinkRecord("contains", "resource:b", "resource:c"))
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=(resource,),
                release=release,
            ),
            object_type_names=frozenset({"Resource"}),
        ),
        object_types={"Resource": resource},
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    handler = SecuredTypedPathNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    node = _node(
        "typed-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-target",),
        arguments={
            "steps": [
                {
                    "link_type": "contains",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                    "max_hops": 2,
                }
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    roots = QueryTable(
        rows=(QueryRow.from_values("resource:a", {"id": "resource:a"}),),
        complete=True,
    )

    result = await handler(node, {"resolve-target": QueryNodeResult(value=roots)})

    assert isinstance(result.value, QueryTable)
    assert tuple(row.row_id for row in result.value.rows) == ("resource:b", "resource:c")
    assert result.value.complete is True


async def test_secured_typed_path_expands_taxonomy_to_observed_resources() -> None:
    resource_class = OntologyObjectType(
        schema_version="1.0.0",
        name="ResourceClass",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    resource_type = OntologyObjectType(
        schema_version="1.0.0",
        name="ResourceType",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    membership = OntologyLinkType(
        schema_version="1.0.0",
        name="resource_type_member_of_class",
        version="1.0.0",
        from_type="ResourceType",
        to_type="ResourceClass",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    classification = OntologyLinkType(
        schema_version="1.0.0",
        name="resource_classified_as",
        version="1.0.0",
        from_type="Resource",
        to_type="ResourceType",
        cardinality=LinkCardinality.MANY_TO_ONE,
    )
    release = build_ontology_release(
        object_types=(resource_class, resource_type, resource),
        link_types=(membership, classification),
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(resource_class, resource_type, resource),
        link_types=(membership, classification),
    )
    for record in (
        OntologyObjectRecord(
            id="class.workload",
            object_type="ResourceClass",
            properties={"id": "class.workload"},
        ),
        OntologyObjectRecord(
            id="compute.vm",
            object_type="ResourceType",
            properties={"id": "compute.vm"},
        ),
        OntologyObjectRecord(
            id="resource:vm",
            object_type="Resource",
            properties={"id": "resource:vm"},
        ),
    ):
        await store.upsert_object(record)
    await store.upsert_link(
        OntologyLinkRecord(
            "resource_type_member_of_class",
            "compute.vm",
            "class.workload",
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(
            "resource_classified_as",
            "resource:vm",
            "compute.vm",
            properties={
                "inventory_generation": "generation-1",
                "mapping_digest": DIGEST,
                "mapping_id": "compute.vm",
                "verified": True,
            },
        )
    )
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=(resource_class, resource_type, resource),
                release=release,
            ),
            object_type_names=frozenset({"ResourceClass", "ResourceType", "Resource"}),
        ),
        object_types={
            "ResourceClass": resource_class,
            "ResourceType": resource_type,
            "Resource": resource,
        },
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    handler = SecuredTypedPathNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    node = _node(
        "taxonomy-path",
        QueryNodeKind.TYPED_PATH,
        dependencies=("resolve-class",),
        arguments={
            "steps": [
                {
                    "link_type": "resource_type_member_of_class",
                    "direction": "incoming",
                    "selector": {"kind": "object_type", "name": "ResourceType"},
                },
                {
                    "link_type": "resource_classified_as",
                    "direction": "incoming",
                    "selector": {"kind": "object_type", "name": "Resource"},
                },
            ],
            "as_of": NOW.isoformat(),
            "purpose": "operations-review",
            "limit": 100,
        },
    )
    roots = QueryTable(
        rows=(QueryRow.from_values("class.workload", {"id": "class.workload"}),),
        complete=True,
    )

    result = await handler(node, {"resolve-class": QueryNodeResult(value=roots)})

    assert isinstance(result.value, QueryTable)
    assert tuple(row.row_id for row in result.value.rows) == ("resource:vm",)
    assert result.value.complete is True


async def test_metric_comparison_uses_reviewed_aggregation_and_equal_windows() -> None:
    registry = MetricSemanticRegistry.build(
        (
            MetricSemanticDefinition(
                concept_id="service.latency",
                provider_metric="latency",
                canonical_unit="ms",
                aggregation=MetricAggregation.AVERAGE,
                description="Service request latency.",
            ),
        )
    )
    baseline = MetricWindow(
        concept_id="service.latency",
        resource_id="service:a",
        unit="ms",
        start=NOW - timedelta(minutes=20),
        end=NOW - timedelta(minutes=10),
        samples=(
            MetricSample(timestamp=NOW - timedelta(minutes=20), value=10.0),
            MetricSample(timestamp=NOW - timedelta(minutes=10), value=20.0),
        ),
        complete=True,
        evidence_refs=("metric:baseline",),
    )
    current = MetricWindow(
        concept_id="service.latency",
        resource_id="service:a",
        unit="ms",
        start=NOW - timedelta(minutes=10),
        end=NOW,
        samples=(
            MetricSample(timestamp=NOW - timedelta(minutes=10), value=30.0),
            MetricSample(timestamp=NOW, value=50.0),
        ),
        complete=True,
        evidence_refs=("metric:current",),
    )
    node = _node(
        "symptom-change",
        QueryNodeKind.METRIC_COMPARISON,
        dependencies=("baseline", "current"),
        output_kind="metric.comparison",
    )

    result = await MetricComparisonNodeHandler(registry=registry)(
        node,
        {
            "baseline": QueryNodeResult(value=baseline),
            "current": QueryNodeResult(value=current),
        },
    )

    assert result.value.baseline_value == 15.0
    assert result.value.current_value == 40.0
    assert result.value.absolute_change == 25.0
    assert result.evidence_refs == ("metric:baseline", "metric:current")


def test_metric_comparison_verifier_requires_two_metric_windows() -> None:
    service, resource, dependency = _catalog()
    release = build_ontology_release(
        object_types=(service, resource),
        link_types=(dependency,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, resource),
        link_types=(dependency,),
    )
    invalid = _node(
        "compare",
        QueryNodeKind.METRIC_COMPARISON,
        dependencies=("resolve-target", "expand-dependencies"),
        output_kind="metric.comparison",
    )
    plan = _plan((_resolution_node(), _traversal_node(), invalid), manifest=manifest)

    with pytest.raises(ValueError, match="dependencies MUST output metric.window"):
        OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                QueryNodeKind.METRIC_COMPARISON,
            ),
            extension_argument_schemas={
                QueryNodeKind.METRIC_COMPARISON: METRIC_ARGUMENT_SCHEMAS[
                    QueryNodeKind.METRIC_COMPARISON
                ]
            },
        ).verify(plan, manifest=manifest)


async def test_hypothesis_join_requires_the_requested_symptom_change() -> None:
    window = MetricWindow(
        concept_id="dependency.latency",
        resource_id="resource:db",
        unit="ms",
        start=NOW - timedelta(minutes=10),
        end=NOW,
        samples=(
            MetricSample(timestamp=NOW - timedelta(minutes=10), value=10.0),
            MetricSample(timestamp=NOW - timedelta(minutes=7), value=20.0),
            MetricSample(timestamp=NOW - timedelta(minutes=3), value=30.0),
            MetricSample(timestamp=NOW, value=40.0),
        ),
        complete=True,
        evidence_refs=("metric:cause",),
    )
    effect = MetricWindow(
        concept_id="service.latency",
        resource_id="service:a",
        unit="ms",
        start=NOW - timedelta(minutes=10),
        end=NOW,
        samples=(
            MetricSample(timestamp=NOW - timedelta(minutes=10), value=40.0),
            MetricSample(timestamp=NOW - timedelta(minutes=7), value=30.0),
            MetricSample(timestamp=NOW - timedelta(minutes=3), value=20.0),
            MetricSample(timestamp=NOW, value=10.0),
        ),
        complete=True,
        evidence_refs=("metric:effect",),
    )
    comparison = MetricWindowComparison(
        concept_id="service.latency",
        resource_id="service:a",
        unit="ms",
        baseline_start=NOW - timedelta(minutes=20),
        baseline_end=NOW - timedelta(minutes=10),
        current_start=NOW - timedelta(minutes=10),
        current_end=NOW,
        baseline_value=40.0,
        current_value=20.0,
        absolute_change=-20.0,
        relative_change=-0.5,
        complete=True,
        reason=None,
        evidence_refs=("metric:comparison",),
    )
    topology = TopologyDiff(
        before_digest=DIGEST,
        after_digest="sha256:" + ("b" * 64),
        added_object_ids=(),
        removed_object_ids=(),
        changed_object_ids=(),
        added_link_keys=(),
        removed_link_keys=(),
        changed_link_keys=(),
        complete=True,
        evidence_refs=("topology:diff",),
        digest="sha256:" + ("c" * 64),
    )
    node = _node(
        "hypothesis-dependency-latency",
        QueryNodeKind.EVIDENCE_JOIN,
        dependencies=("cause", "effect", "topology", "comparison"),
        arguments={
            "feature_cutoff": (NOW - timedelta(minutes=10)).isoformat(),
            "effect_direction": "increase",
        },
        output_kind="causal.join",
    )

    result = await EvidenceJoinNodeHandler()(
        node,
        {
            "cause": QueryNodeResult(value=window),
            "effect": QueryNodeResult(value=effect),
            "topology": QueryNodeResult(value=topology),
            "comparison": QueryNodeResult(value=comparison),
        },
    )

    assert result.value.status is CausalJoinStatus.UNRESOLVED
    assert result.value.limitations == ("symptom_increase_not_observed",)
    assert result.value.temporal_claim is None
    assert "metric:comparison" in result.evidence_refs
