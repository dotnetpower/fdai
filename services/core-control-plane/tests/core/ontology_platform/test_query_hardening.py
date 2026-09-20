"""Regression inputs retained from the ontology query hardening review."""

import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fdai.composition.semantic_query_scoped_sources import scoped_source_handlers
from fdai.core.conversation.semantic_planning_judgment import _semantic_judgment_capabilities
from fdai.core.conversation.semantic_planning_support import (
    _bounded_context,
    _refresh_object_set_cutoffs,
)
from fdai.core.conversation.session import Turn
from fdai.core.ontology_platform import ObjectSelector, ObjectSelectorKind, ObjectSetDefinition
from fdai.core.ontology_platform.query_execution import QueryNodeHeldError, QueryNodeResult
from fdai.core.ontology_platform.query_metric_handlers import METRIC_ARGUMENT_SCHEMAS
from fdai.core.ontology_platform.query_source_handlers import (
    SecuredRelationshipTraversalNodeHandler,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.query_verification import OntologyQueryPlanVerifier
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json
from tests.composition.test_wire_semantic_query import _metric_registry
from tests.core.ontology_platform.test_query_gateway import (
    _definition,
    _gateway_with_records,
    _object_type,
    _request,
)
from tests.core.ontology_platform.test_query_verification import NOW, _manifest, _plan


async def test_exact_ids_preserve_links_between_selected_records() -> None:
    gateway = await _gateway_with_records(
        _object_type(),
        *(
            OntologyObjectRecord(id=identity, object_type="Resource", properties={"id": identity})
            for identity in ("a", "b")
        ),
        links=(OntologyLinkRecord(from_id="a", link_type="depends_on", to_id="b"),),
    )
    result = await gateway.materialize(
        _definition().model_copy(update={"object_ids": ("a", "b")}), projection_request=_request()
    )
    assert result.receipt.complete
    assert len(result.materialization.graph.links) == 1


@pytest.mark.parametrize("transitive", [False, True])
async def test_two_hop_relationship_keeps_every_reached_endpoint(transitive: bool) -> None:
    gateway = await _gateway_with_records(
        _object_type(),
        *(
            OntologyObjectRecord(id=identity, object_type="Resource", properties={"id": identity})
            for identity in ("a", "b", "c")
        ),
        links=(
            OntologyLinkRecord(from_id="a", link_type="depends_on", to_id="b"),
            OntologyLinkRecord(from_id="b", link_type="depends_on", to_id="c"),
        ),
        transitive=transitive,
    )
    node = OntologyQueryNode(
        node_id="traverse",
        kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        depends_on=("root",),
        arguments_json=canonical_json(
            {
                "selector": {"kind": "object_type", "name": "Resource"},
                "link_types": ["depends_on"],
                "direction": "outgoing",
                "max_depth": 2,
                "as_of": _definition().as_of.isoformat(),
                "purpose": "operations-review",
                "limit": 10,
            }
        ),
        output_kind="query.table",
    )
    result = await SecuredRelationshipTraversalNodeHandler(
        gateway, caller_role=CeilingRole.READER, purposes=("operations-review",)
    )(
        node,
        {
            "root": QueryNodeResult(
                QueryTable(rows=(QueryRow.from_values("a", {"id": "a"}),), complete=True)
            )
        },
    )
    assert {row.row_id for row in result.value.rows} == ({"b", "c"} if transitive else {"b"})
    assert result.value.complete

    handler = SecuredRelationshipTraversalNodeHandler(
        gateway, caller_role=CeilingRole.READER, purposes=("operations-review",)
    )
    stale_source = QueryTable(
        rows=(QueryRow.from_values("a", {"id": "a"}),),
        complete=True,
        source_generation="another-generation",
    )
    with pytest.raises(QueryNodeHeldError, match="query_source_generation_conflict"):
        await handler(node, {"root": QueryNodeResult(stale_source)})
    fresh_node = node.model_copy(
        update={"arguments_json": canonical_json({**node.arguments, "freshness_seconds": 1})}
    )
    with pytest.raises(QueryNodeHeldError, match="graph_freshness_unavailable"):
        await handler(
            fresh_node, {"root": QueryNodeResult(QueryTable(rows=stale_source.rows, complete=True))}
        )


def test_latest_trusted_context_survives_long_earlier_turn() -> None:
    context = _bounded_context(
        (
            Turn(turn_id="old", direction="outbound", content="x" * 12000),
            Turn(turn_id="bound", direction="system", content="selected-target: resource-a"),
        )
    )
    assert context[-1] == "system:selected-target: resource-a"
    assert sum(len(item.split(":", 1)[1]) for item in context) <= 12000


@pytest.mark.parametrize(
    "kind",
    [
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.TYPED_PATH,
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
    ],
)
def test_every_current_read_cutoff_is_rebound(kind: QueryNodeKind) -> None:
    node = OntologyQueryNode(
        node_id="current",
        kind=kind,
        arguments_json=canonical_json({"as_of": NOW.isoformat()}),
        output_kind="query.table",
    )
    refreshed = _refresh_object_set_cutoffs(
        _plan((node,), release_digest="sha256:" + "a" * 64, manifest_digest="sha256:" + "b" * 64),
        execution_time=NOW + timedelta(seconds=10),
    )
    assert refreshed.nodes[0].arguments["as_of"] == (NOW + timedelta(seconds=10)).isoformat()


@pytest.mark.parametrize("duration", [-1, 0, 32 * 86400])
def test_invalid_metric_interval_is_rejected_before_io(duration: int) -> None:
    release, manifest = _manifest()
    node = OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SERIES,
        arguments_json=canonical_json(
            {
                "concept_id": "cpu",
                "resource_id": "resource-a",
                "start": NOW.isoformat(),
                "end": (NOW + timedelta(seconds=duration)).isoformat(),
            }
        ),
        output_kind="metric.window",
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.METRIC_SERIES,),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SERIES: METRIC_ARGUMENT_SCHEMAS[QueryNodeKind.METRIC_SERIES]
        },
        reviewed_metric_concepts=("cpu",),
    )
    with pytest.raises(ValueError, match="metric interval"):
        verifier.verify(
            _plan((node,), release_digest=release.digest, manifest_digest=manifest.manifest_digest),
            manifest=manifest,
        )


@pytest.mark.parametrize("kind", [QueryNodeKind.PROJECT, QueryNodeKind.ORDER])
def test_hidden_and_unknown_projection_fields_are_rejected(kind: QueryNodeKind) -> None:
    release, manifest = _manifest()
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
    )
    source = OntologyQueryNode(
        node_id="source",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
        output_kind="query.table",
    )
    for field in ("properties.secret", "properties.missing"):
        arguments = (
            {"fields": [field]}
            if kind is QueryNodeKind.PROJECT
            else {"keys": [{"field": field, "direction": "ascending"}]}
        )
        output = OntologyQueryNode(
            node_id="output",
            kind=kind,
            depends_on=("source",),
            arguments_json=canonical_json(arguments),
            output_kind="query.table",
        )
        with pytest.raises(ValueError, match="absent from dependency output schema"):
            OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET, kind)).verify(
                _plan(
                    (source, output),
                    release_digest=release.digest,
                    manifest_digest=manifest.manifest_digest,
                ),
                manifest=manifest,
            )


def test_large_property_projection_omits_partial_canonical_values() -> None:
    result = _semantic_judgment_capabilities(
        (
            {
                "kind": "object",
                "name": "Example",
                "key": "id",
                "properties": {"id": {}, **{f"property_{index}": {} for index in range(40)}},
            },
        )
    )
    assert result[0]["name"] == "Example"
    assert "canonical_values" not in result[0]
    assert "canonical_values_omitted" not in result[0]


def test_capability_budget_keeps_a_deterministic_ranked_prefix() -> None:
    descriptors = tuple(
        {"kind": "function", "name": f"query.{index}" + "x" * 90} for index in range(512)
    )
    result = _semantic_judgment_capabilities(descriptors)

    assert 0 < len(result) < len(descriptors)
    assert [item["name"] for item in result] == [
        descriptor["name"] for descriptor in descriptors[: len(result)]
    ]
    assert len(json.dumps(result, separators=(",", ":"), sort_keys=True).encode()) <= 32 * 1024


async def test_unknown_metric_target_never_calls_provider() -> None:
    declaration = _object_type()
    gateway = await _gateway_with_records(declaration)
    provider = AsyncMock()
    handlers = scoped_source_handlers(
        gateway=gateway,
        projection_request=_request(),
        purpose="operations-review",
        release_digest="sha256:" + "a" * 64,
        object_types={"Resource": declaration},
        now=lambda: _definition().as_of,
        topology_reader=None,
        metric_registry=_metric_registry(),
        metric_provider=provider,
    )
    node = OntologyQueryNode(
        node_id="metric",
        kind=QueryNodeKind.METRIC_SERIES,
        arguments_json=canonical_json(
            {
                "concept_id": "requests.count",
                "resource_id": "not-visible",
                "start": NOW.isoformat(),
                "end": (NOW + timedelta(minutes=1)).isoformat(),
            }
        ),
        output_kind="metric.window",
    )
    with pytest.raises(PermissionError, match="authorized Resource scope"):
        await handlers[QueryNodeKind.METRIC_SERIES](node, {})
    provider.read.assert_not_awaited()
