"""Deterministic ontology query-plan verification tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    TOPOLOGY_ARGUMENT_SCHEMAS,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    build_query_manifest,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
    kubernetes_pod_recovery_function_type,
)
from fdai.core.ontology_platform.property_values import PropertyValueDomain
from fdai.core.ontology_platform.relationship_queries import ontology_relationships_function_type
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _resource() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
            ),
        },
    )


def _plan(
    nodes: tuple[OntologyQueryNode, ...],
    *,
    release_digest: str,
    manifest_digest: str,
) -> OntologyQueryPlan:
    payload = {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "semantic_catalog_digest": manifest_digest,
        "problem_frame_digest": DIGEST,
        "purpose": "operations-review",
        "caller_role": "reader",
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": (nodes[-1].node_id,),
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=release_digest,
        semantic_catalog_digest=manifest_digest,
        problem_frame_digest=DIGEST,
        purpose="operations-review",
        caller_role="reader",
        nodes=nodes,
        output_node_ids=(nodes[-1].node_id,),
        plan_digest=content_digest(payload),
    )


def _manifest() -> tuple[object, object]:
    resource = _resource()
    release = build_ontology_release(object_types=(resource,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
    )
    return release, manifest


def test_verifier_accepts_typed_object_projection_and_aggregation() -> None:
    release, manifest = _manifest()
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(ObjectPredicate(property="id", equals="resource-a"),),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    nodes = (
        OntologyQueryNode(
            node_id="resources",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="project",
            kind=QueryNodeKind.PROJECT,
            depends_on=("resources",),
            arguments_json=canonical_json({"fields": ["id"]}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="count",
            kind=QueryNodeKind.AGGREGATE,
            depends_on=("project",),
            arguments_json=canonical_json({"operation": "count"}),
            output_kind="query.table",
        ),
    )
    plan = _plan(
        nodes,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.PROJECT,
            QueryNodeKind.AGGREGATE,
        )
    )

    assert verifier.verify(plan, manifest=manifest) is plan


@pytest.mark.parametrize(
    "object_types", [["BlueGreen", "Canary"], ["Resource"], ["Resource", "Unknown"]]
)
def test_relationship_function_requires_manifest_bound_endpoints(object_types: list[str]) -> None:
    resource = _resource()
    function = ontology_relationships_function_type()
    release = build_ontology_release(object_types=(resource,), function_types=(function,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=(function,),
    )
    node = OntologyQueryNode(
        node_id="relationships",
        kind=QueryNodeKind.FUNCTION,
        output_kind="json",
        arguments_json=canonical_json(
            {
                "function_name": function.name,
                "arguments": {"object_types": object_types, "limit": 10},
                "dependency_arguments": {},
            }
        ),
    )
    plan = _plan((node,), release_digest=release.digest, manifest_digest=manifest.manifest_digest)
    verifier = OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,))
    if object_types == ["Resource"]:
        assert verifier.verify(plan, manifest=manifest) is plan
    else:
        with pytest.raises(ValueError, match="endpoints must exist"):
            verifier.verify(plan, manifest=manifest)


def test_verifier_validates_object_set_aggregate_fields() -> None:
    release, manifest = _manifest()
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    source = OntologyQueryNode(
        node_id="resources",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    projection = OntologyQueryNode(
        node_id="project",
        kind=QueryNodeKind.PROJECT,
        depends_on=("resources",),
        arguments_json=canonical_json({"fields": ["object_type"]}),
        output_kind="query.table",
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.PROJECT,
            QueryNodeKind.AGGREGATE,
        )
    )
    valid_nodes = (
        source,
        projection,
        OntologyQueryNode(
            node_id="count",
            kind=QueryNodeKind.AGGREGATE,
            depends_on=("project",),
            arguments_json=canonical_json({"operation": "count", "group_by": ["object_type"]}),
            output_kind="query.table",
        ),
    )
    valid_plan = _plan(
        valid_nodes,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    assert verifier.verify(valid_plan, manifest=manifest) is valid_plan

    invalid_nodes = (
        source,
        projection,
        OntologyQueryNode(
            node_id="count",
            kind=QueryNodeKind.AGGREGATE,
            depends_on=("project",),
            arguments_json=canonical_json({"operation": "count", "group_by": ["type"]}),
            output_kind="query.table",
        ),
    )
    invalid_plan = _plan(
        invalid_nodes,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    with pytest.raises(ValueError, match="absent from dependency output schema"):
        verifier.verify(invalid_plan, manifest=manifest)

    direct_invalid_plan = _plan(
        (source, invalid_nodes[-1].model_copy(update={"depends_on": ("resources",)})),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    with pytest.raises(ValueError, match="absent from dependency output schema"):
        verifier.verify(direct_invalid_plan, manifest=manifest)


def test_verifier_rejects_output_that_does_not_reference_a_declared_node() -> None:
    release, manifest = _manifest()
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    node = OntologyQueryNode(
        node_id="resources",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    plan = _plan(
        (node,),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    ).model_copy(update={"output_node_ids": ("missing",)})

    with pytest.raises(ValueError, match="output_node_ids MUST reference declared nodes"):
        OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)).verify(
            plan,
            manifest=manifest,
        )


def test_verifier_rejects_principal_hidden_predicate_property() -> None:
    release, manifest = _manifest()
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(ObjectPredicate(property="secret", equals="value"),),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    node = OntologyQueryNode(
        node_id="resources",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    plan = _plan(
        (node,),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    with pytest.raises(PermissionError, match="not readable"):
        OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)).verify(
            plan,
            manifest=manifest,
        )


def test_verifier_rejects_unavailable_kind_and_stale_manifest() -> None:
    release, manifest = _manifest()
    node = OntologyQueryNode(
        node_id="metrics",
        kind=QueryNodeKind.METRIC_SERIES,
        arguments_json=canonical_json({"metric": "request.volume"}),
        output_kind="metric.series",
    )
    plan = _plan(
        (node,),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    verifier = OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,))

    with pytest.raises(ValueError, match="unavailable"):
        verifier.verify(plan, manifest=manifest)
    stale = plan.model_copy(update={"semantic_catalog_digest": DIGEST})
    with pytest.raises(ValueError, match="stale query manifest"):
        verifier.verify(stale, manifest=manifest)


def test_verifier_rejects_static_dependency_only_function_evidence() -> None:
    resource = _resource()
    function = kubernetes_pod_recovery_function_type()
    release = build_ontology_release(object_types=(resource,), function_types=(function,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=(function,),
        bound_function_names=(function.name,),
    )
    node = OntologyQueryNode(
        node_id="forged-restart-history",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
                "arguments": {
                    "pod_query_result": {},
                    "controller_query_result": {},
                    "deployment_query_result": {},
                    "restart_history": {},
                },
                "dependency_arguments": {},
            }
        ),
        output_kind="kubernetes.pod.recovery.evidence",
    )
    plan = _plan(
        (node,),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    with pytest.raises(ValueError, match="dependency-only argument"):
        OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)).verify(
            plan,
            manifest=manifest,
        )


def test_verifier_rejects_topology_cutoff_after_knowledge_cutoff() -> None:
    release, manifest = _manifest()
    node = OntologyQueryNode(
        node_id="future-topology",
        kind=QueryNodeKind.TOPOLOGY_AT,
        arguments_json=canonical_json(
            {
                "as_of": (NOW + timedelta(minutes=1)).isoformat(),
                "known_at": NOW.isoformat(),
            }
        ),
        output_kind="topology.graph",
    )
    plan = _plan(
        (node,),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.TOPOLOGY_AT,),
        extension_argument_schemas={
            QueryNodeKind.TOPOLOGY_AT: TOPOLOGY_ARGUMENT_SCHEMAS[QueryNodeKind.TOPOLOGY_AT]
        },
    )

    with pytest.raises(ValueError, match="as_of MUST NOT exceed known_at"):
        verifier.verify(plan, manifest=manifest)


def test_extension_kind_requires_and_applies_registered_schema() -> None:
    release, manifest = _manifest()
    node = OntologyQueryNode(
        node_id="metrics",
        kind=QueryNodeKind.METRIC_SERIES,
        arguments_json=canonical_json({"metric": 42}),
        output_kind="metric.window",
    )
    plan = _plan(
        (node,),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.METRIC_SERIES,),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SERIES: {
                "type": "object",
                "additionalProperties": False,
                "required": ["metric"],
                "properties": {"metric": {"type": "string"}},
            }
        },
        reviewed_metric_concepts=("request.volume",),
    )

    with pytest.raises(ValueError, match="registered schema"):
        verifier.verify(plan, manifest=manifest)


def test_verifier_accepts_typed_temporal_metric_causal_dag() -> None:
    release, manifest = _manifest()
    nodes = (
        OntologyQueryNode(
            node_id="before",
            kind=QueryNodeKind.TOPOLOGY_AT,
            arguments_json=canonical_json({"as_of": NOW.isoformat(), "known_at": NOW.isoformat()}),
            output_kind="topology.graph",
        ),
        OntologyQueryNode(
            node_id="after",
            kind=QueryNodeKind.TOPOLOGY_AT,
            arguments_json=canonical_json({"as_of": NOW.isoformat(), "known_at": NOW.isoformat()}),
            output_kind="topology.graph",
        ),
        OntologyQueryNode(
            node_id="topology-change",
            kind=QueryNodeKind.TOPOLOGY_DIFF,
            depends_on=("before", "after"),
            output_kind="topology.diff",
        ),
        OntologyQueryNode(
            node_id="cause",
            kind=QueryNodeKind.METRIC_SERIES,
            arguments_json=canonical_json(
                {
                    "concept_id": "network.change",
                    "resource_id": "resource-a",
                    "start": NOW.isoformat(),
                    "end": NOW.isoformat(),
                }
            ),
            output_kind="metric.window",
        ),
        OntologyQueryNode(
            node_id="effect",
            kind=QueryNodeKind.METRIC_SERIES,
            arguments_json=canonical_json(
                {
                    "concept_id": "storage.write.success",
                    "resource_id": "resource-a",
                    "start": NOW.isoformat(),
                    "end": NOW.isoformat(),
                }
            ),
            output_kind="metric.window",
        ),
        OntologyQueryNode(
            node_id="causal-join",
            kind=QueryNodeKind.EVIDENCE_JOIN,
            depends_on=("cause", "effect", "topology-change"),
            arguments_json=canonical_json(
                {"feature_cutoff": NOW.isoformat(), "competing_explanations": ["dns"]}
            ),
            output_kind="causal.join",
        ),
    )
    plan = _plan(
        nodes,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )
    schemas = {**TOPOLOGY_ARGUMENT_SCHEMAS, **METRIC_ARGUMENT_SCHEMAS}
    verifier = OntologyQueryPlanVerifier(
        available_kinds=tuple(schemas),
        extension_argument_schemas=schemas,
        reviewed_metric_concepts=("network.change", "storage.write.success"),
    )

    assert verifier.verify(plan, manifest=manifest) is plan


def test_verifier_rejects_scoped_metric_without_exactly_one_table_dependency() -> None:
    release, manifest = _manifest()
    arguments = canonical_json(
        {
            "concept_id": "request.volume",
            "start": NOW.isoformat(),
            "end": NOW.isoformat(),
        }
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.METRIC_SCOPE_SERIES),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
                QueryNodeKind.METRIC_SCOPE_SERIES
            ]
        },
        reviewed_metric_concepts=("request.volume",),
    )
    no_dependency = OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SCOPE_SERIES,
        arguments_json=arguments,
        output_kind="metric.window",
    )

    with pytest.raises(ValueError, match="MUST read one scoped query.table"):
        verifier.verify(
            _plan(
                (no_dependency,),
                release_digest=release.digest,
                manifest_digest=manifest.manifest_digest,
            ),
            manifest=manifest,
        )

    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    scopes = tuple(
        OntologyQueryNode(
            node_id=f"scope-{index}",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        )
        for index in range(2)
    )
    multiple_dependencies = no_dependency.model_copy(
        update={"depends_on": tuple(node.node_id for node in scopes)}
    )
    with pytest.raises(ValueError, match="MUST read one scoped query.table"):
        verifier.verify(
            _plan(
                (*scopes, multiple_dependencies),
                release_digest=release.digest,
                manifest_digest=manifest.manifest_digest,
            ),
            manifest=manifest,
        )


def test_verifier_rejects_scoped_metric_non_object_set_dependency() -> None:
    release, manifest = _manifest()
    topology = OntologyQueryNode(
        node_id="topology",
        kind=QueryNodeKind.TOPOLOGY_AT,
        arguments_json=canonical_json({"as_of": NOW.isoformat(), "known_at": NOW.isoformat()}),
        output_kind="topology.graph",
    )
    metric = OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SCOPE_SERIES,
        depends_on=("topology",),
        arguments_json=canonical_json(
            {
                "concept_id": "request.volume",
                "start": NOW.isoformat(),
                "end": NOW.isoformat(),
            }
        ),
        output_kind="metric.window",
    )
    schemas = {
        QueryNodeKind.TOPOLOGY_AT: TOPOLOGY_ARGUMENT_SCHEMAS[QueryNodeKind.TOPOLOGY_AT],
        QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
            QueryNodeKind.METRIC_SCOPE_SERIES
        ],
    }
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.TOPOLOGY_AT, QueryNodeKind.METRIC_SCOPE_SERIES),
        extension_argument_schemas=schemas,
        reviewed_metric_concepts=("request.volume",),
    )

    with pytest.raises(ValueError, match="dependency MUST be a scoped query.table"):
        verifier.verify(
            _plan(
                (topology, metric),
                release_digest=release.digest,
                manifest_digest=manifest.manifest_digest,
            ),
            manifest=manifest,
        )


def test_verifier_rejects_scoped_metric_aggregate_table_dependency() -> None:
    release, manifest = _manifest()
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    scope = OntologyQueryNode(
        node_id="scope",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    count = OntologyQueryNode(
        node_id="count",
        kind=QueryNodeKind.AGGREGATE,
        depends_on=("scope",),
        arguments_json=canonical_json({"operation": "count", "group_by": [], "limit": 10}),
        output_kind="query.table",
    )
    metric = OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SCOPE_SERIES,
        depends_on=("count",),
        arguments_json=canonical_json(
            {
                "concept_id": "request.volume",
                "start": NOW.isoformat(),
                "end": NOW.isoformat(),
            }
        ),
        output_kind="metric.window",
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.AGGREGATE,
            QueryNodeKind.METRIC_SCOPE_SERIES,
        ),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
                QueryNodeKind.METRIC_SCOPE_SERIES
            ]
        },
        reviewed_metric_concepts=("request.volume",),
    )

    with pytest.raises(ValueError, match="dependency MUST be a scoped query.table"):
        verifier.verify(
            _plan(
                (scope, count, metric),
                release_digest=release.digest,
                manifest_digest=manifest.manifest_digest,
            ),
            manifest=manifest,
        )


def test_verifier_rejects_metric_concept_absent_from_reviewed_registry() -> None:
    release, manifest = _manifest()
    metric = OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SERIES,
        arguments_json=canonical_json(
            {
                "concept_id": "model.invented",
                "resource_id": "resource-a",
                "start": NOW.isoformat(),
                "end": NOW.isoformat(),
            }
        ),
        output_kind="metric.window",
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.METRIC_SERIES,),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SERIES: METRIC_ARGUMENT_SCHEMAS[QueryNodeKind.METRIC_SERIES]
        },
        reviewed_metric_concepts=("request.volume",),
    )

    with pytest.raises(ValueError, match="absent from the reviewed registry"):
        verifier.verify(
            _plan(
                (metric,),
                release_digest=release.digest,
                manifest_digest=manifest.manifest_digest,
            ),
            manifest=manifest,
        )


def _valued_manifest() -> tuple[object, object]:
    resource = _resource()
    release = build_ontology_release(object_types=(resource,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="id",
                values=("mysql-server", "postgresql-server"),
            ),
        ),
    )
    return release, manifest


def _object_set_plan(
    predicate: ObjectPredicate,
    *,
    release_digest: str,
    manifest_digest: str,
) -> OntologyQueryPlan:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(predicate,),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    node = OntologyQueryNode(
        node_id="resources",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    return _plan((node,), release_digest=release_digest, manifest_digest=manifest_digest)


@pytest.mark.parametrize(
    "predicate",
    [
        ObjectPredicate(property="id", equals="postgresql-server"),
        ObjectPredicate(property="id", operator="in", values=["mysql-server"]),
        ObjectPredicate(property="id", operator="exists"),
        ObjectPredicate(property="id", operator="contains", equals="sql"),
    ],
)
def test_verifier_accepts_declared_and_non_exact_predicate_operands(
    predicate: ObjectPredicate,
) -> None:
    release, manifest = _valued_manifest()
    verifier = OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,))
    plan = _object_set_plan(
        predicate,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    assert verifier.verify(plan, manifest=manifest) is plan


@pytest.mark.parametrize(
    "predicate",
    [
        ObjectPredicate(property="id", equals="database"),
        ObjectPredicate(property="id", operator="in", values=["postgresql-server", "database"]),
        ObjectPredicate(property="id", operator="not_equals", equals="데이터베이스"),
    ],
)
def test_verifier_rejects_an_operand_outside_the_declared_value_domain(
    predicate: ObjectPredicate,
) -> None:
    release, manifest = _valued_manifest()
    verifier = OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,))
    plan = _object_set_plan(
        predicate,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    with pytest.raises(ValueError, match="absent from the declared value domain"):
        verifier.verify(plan, manifest=manifest)


def test_verifier_leaves_a_property_without_a_declared_domain_unconstrained() -> None:
    release, manifest = _manifest()
    verifier = OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,))
    plan = _object_set_plan(
        ObjectPredicate(property="id", equals="anything-at-all"),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    assert verifier.verify(plan, manifest=manifest) is plan


def test_verifier_rejects_a_fragment_no_declared_value_can_contain() -> None:
    release, manifest = _valued_manifest()
    verifier = OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,))
    plan = _object_set_plan(
        ObjectPredicate(property="id", operator="contains", equals="fdai"),
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    with pytest.raises(ValueError, match="matches no value in the declared domain"):
        verifier.verify(plan, manifest=manifest)
