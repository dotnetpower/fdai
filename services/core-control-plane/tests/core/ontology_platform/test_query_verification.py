"""Deterministic ontology query-plan verification tests."""

from __future__ import annotations

from datetime import UTC, datetime

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
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.AGGREGATE)
    )
    valid_nodes = (
        source,
        OntologyQueryNode(
            node_id="count",
            kind=QueryNodeKind.AGGREGATE,
            depends_on=("resources",),
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
        OntologyQueryNode(
            node_id="count",
            kind=QueryNodeKind.AGGREGATE,
            depends_on=("resources",),
            arguments_json=canonical_json({"operation": "count", "group_by": ["type"]}),
            output_kind="query.table",
        ),
    )
    invalid_plan = _plan(
        invalid_nodes,
        release_digest=release.digest,
        manifest_digest=manifest.manifest_digest,
    )

    with pytest.raises(ValueError, match="absent from object_set output schema"):
        verifier.verify(invalid_plan, manifest=manifest)


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
    )

    assert verifier.verify(plan, manifest=manifest) is plan
