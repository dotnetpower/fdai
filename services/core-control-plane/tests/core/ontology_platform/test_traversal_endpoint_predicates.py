"""Relationship traversal endpoint predicates filter reached endpoints only."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.ontology_platform import ObjectPredicate, ObjectPredicateOperator
from fdai.core.ontology_platform.object_sets import object_matches_predicates
from fdai.core.ontology_platform.query_execution import QueryNodeHeldError, QueryNodeResult
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


async def test_an_empty_filtered_result_completes_with_its_own_receipt() -> None:
    authority = SecuredQueryReceiptAuthority(now=lambda: NOW)
    handler = SecuredRelationshipTraversalNodeHandler(
        await fixture_gateway(),
        caller_role=CeilingRole.READER,
        purposes=(PURPOSE,),
        receipt_authority=authority,
    )
    node = _traversal([{"property": "type", "operator": "equals", "equals": "llm-endpoint"}])

    result = await handler(node, _group_row())
    issued = authority._resolve_issued(result.evidence_refs)

    assert result.value.rows == ()
    assert result.value.complete
    assert sum(ref.startswith("ontology-object-set-output:") for ref in result.evidence_refs) == 1
    # The re-read observed every reached endpoint, so the empty result carries the generation.
    assert issued.receipt.source_generation == result.value.source_generation is not None


class _DriftingGateway:
    """Report a newer generation for the exact endpoint re-read than for the traversal."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def materialize(self, definition: Any, **kwargs: Any) -> Any:
        secured = await self._inner.materialize(definition, **kwargs)
        if definition.object_ids is None:
            return secured
        return secured.model_copy(
            update={"receipt": secured.receipt.model_copy(update={"source_generation": "newer"})}
        )


@pytest.mark.parametrize("kept", ("llm-endpoint", "network.subnet"))
async def test_a_filtered_result_from_a_newer_generation_is_held(kept: str) -> None:
    handler = SecuredRelationshipTraversalNodeHandler(
        _DriftingGateway(await fixture_gateway()),  # type: ignore[arg-type]
        caller_role=CeilingRole.READER,
        purposes=(PURPOSE,),
        receipt_authority=SecuredQueryReceiptAuthority(now=lambda: NOW),
    )
    node = _traversal([{"property": "type", "operator": "equals", "equals": kept}])

    with pytest.raises(QueryNodeHeldError, match="query_source_generation_conflict"):
        await handler(node, _group_row())


@pytest.mark.parametrize("operand", (7, True, ["rg-app"]))
def test_case_insensitive_equality_requires_a_text_operand(operand: object) -> None:
    with pytest.raises(ValueError, match="string operand"):
        ObjectPredicate(
            property="name", operator=ObjectPredicateOperator.EQUALS_IGNORE_CASE, equals=operand
        )


@pytest.mark.parametrize(
    ("value", "operand", "matches"),
    (
        ("RG-Payments", "rg-payments", True),
        ("rg-payments-dev", "rg-payments", False),
        (7, "7", False),
    ),
)
def test_case_insensitive_equality_is_exact_apart_from_case(
    value: object, operand: str, matches: bool
) -> None:
    predicate = ObjectPredicate(
        property="name", operator=ObjectPredicateOperator.EQUALS_IGNORE_CASE, equals=operand
    )

    assert object_matches_predicates({"name": value}, (predicate,)) is matches
    assert predicate.model_dump(mode="json") == {
        "property": "name",
        "operator": "equals_ignore_case",
        "equals": operand,
    }
