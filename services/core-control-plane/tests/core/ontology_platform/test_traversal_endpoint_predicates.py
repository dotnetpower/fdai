"""Relationship traversal endpoint predicates filter reached endpoints only."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.ontology_platform.query_execution import QueryNodeResult
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.query_source_handlers import (
    SecuredRelationshipTraversalNodeHandler,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import CeilingRole
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)
from tests.conversation.semantic_reasoning_support import (
    NOW,
    PURPOSE,
    fixture_gateway,
    plan_verifier,
    production_manifest,
)


def _traversal(predicates: list[dict[str, Any]], *, max_depth: int = 5) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id="members",
        kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        depends_on=("group",),
        arguments_json=canonical_json(
            {
                "selector": {"kind": "object_type", "name": "Resource"},
                "link_types": ["contains"],
                "direction": "outgoing",
                "max_depth": max_depth,
                "as_of": NOW.isoformat(),
                "purpose": PURPOSE,
                "limit": 100,
                **({"endpoint_predicates": predicates} if predicates else {}),
            }
        ),
        output_kind="query.table",
    )


def _group_row() -> dict[str, QueryNodeResult]:
    table = QueryTable(
        rows=(QueryRow.from_values("rg-1", {"id": "rg-1"}),),
        complete=True,
        source_generation="fixture-generation",
    )
    return {"group": QueryNodeResult(table)}


def _plan(traversal: OntologyQueryNode) -> OntologyQueryPlan:
    manifest = production_manifest()
    anchor = OntologyQueryNode(
        node_id="group",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json(
            {
                "definition": {
                    "selector": {"kind": "object_type", "name": "Resource"},
                    "predicates": [{"property": "name", "operator": "equals", "equals": "rg-app"}],
                    "as_of": NOW.isoformat(),
                    "purpose": PURPOSE,
                    "limit": 2,
                }
            }
        ),
        output_kind="query.table",
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": "sha256:" + "b" * 64,
        "purpose": PURPOSE,
        "caller_role": manifest.principal_role.value,
        "nodes": [anchor.model_dump(mode="json"), traversal.model_dump(mode="json")],
        "output_node_ids": ["members"],
        "execution_authority": False,
    }
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


async def test_filtered_intermediates_still_carry_the_transitive_path() -> None:
    handler = SecuredRelationshipTraversalNodeHandler(
        await fixture_gateway(), caller_role=CeilingRole.READER, purposes=(PURPOSE,)
    )
    node = _traversal([{"property": "type", "operator": "equals", "equals": "network.subnet"}])

    result = await handler(node, _group_row())

    assert [row.row_id for row in result.value.rows] == ["snet-1"]
    assert result.value.complete
    assert not any(ref.startswith("ontology-object-set-output:") for ref in result.evidence_refs)


async def test_issued_output_receipt_covers_exactly_the_filtered_endpoints() -> None:
    authority = SecuredQueryReceiptAuthority(now=lambda: NOW)
    handler = SecuredRelationshipTraversalNodeHandler(
        await fixture_gateway(),
        caller_role=CeilingRole.READER,
        purposes=(PURPOSE,),
        receipt_authority=authority,
    )
    node = _traversal(
        [{"property": "type", "operator": "not_equals", "equals": "authorization.role-assignment"}]
    )

    result = await handler(node, _group_row())
    # The fixture graph carries no decision evidence, so resolve the issued result directly.
    issued = authority._resolve_issued(result.evidence_refs)

    assert "ra-1" not in {row.row_id for row in result.value.rows}
    assert {item.id for item in issued.materialization.graph.objects} == {
        row.row_id for row in result.value.rows
    }


async def test_unfiltered_traversal_keeps_its_materialization_marker() -> None:
    handler = SecuredRelationshipTraversalNodeHandler(
        await fixture_gateway(), caller_role=CeilingRole.READER, purposes=(PURPOSE,)
    )

    result = await handler(_traversal([], max_depth=1), _group_row())

    assert "ra-1" in {row.row_id for row in result.value.rows}
    assert sum(ref.startswith("ontology-object-set-output:") for ref in result.evidence_refs) == 1


@pytest.mark.parametrize(
    ("predicate", "error"),
    (
        ({"property": "owner_secret", "operator": "exists"}, PermissionError),
        ({"property": "type", "operator": "equals", "equals": "not-a-type"}, ValueError),
    ),
)
def test_verifier_checks_endpoint_predicates_like_object_set_predicates(
    predicate: dict[str, Any], error: type[Exception]
) -> None:
    with pytest.raises(error):
        plan_verifier().verify(_plan(_traversal([predicate])), manifest=production_manifest())


def test_verifier_accepts_declared_endpoint_predicates() -> None:
    plan = _plan(_traversal([{"property": "type", "operator": "equals", "equals": "compute.vm"}]))

    assert plan_verifier().verify(plan, manifest=production_manifest()) is plan
