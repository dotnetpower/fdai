"""Downstream functions must receive path endpoints, not a carried gateway root."""

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    QueryNodeResult,
    QueryRow,
    QueryTable,
    SecuredTypedPathNodeHandler,
    compile_interfaces,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing.ontology_instance import InMemoryOntologyInstanceStore
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

NOW = datetime(2026, 9, 6, tzinfo=UTC)


@pytest.mark.parametrize("key", ["id", "name"])
@pytest.mark.parametrize("has_backend", [False, True])
async def test_function_receipt_resolves_only_verified_path_endpoints(key, has_backend):
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key=key,
        properties={key: PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="routes_to",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    release = build_ontology_release(object_types=(resource,), link_types=(link,))
    store = InMemoryOntologyInstanceStore(object_types=(resource,), link_types=(link,))
    await store.upsert_object(
        OntologyObjectRecord(id="gateway", object_type="Resource", properties={key: "gateway"})
    )
    if has_backend:
        await store.upsert_object(
            OntologyObjectRecord(id="backend", object_type="Resource", properties={key: "backend"})
        )
        await store.upsert_link(
            OntologyLinkRecord(
                link_type="routes_to",
                from_id="gateway",
                to_id="backend",
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
    root = await gateway.materialize(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            object_ids=("gateway",),
            as_of=NOW,
            purpose="operations-review",
        ),
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER, declared_purposes=frozenset({"operations-review"})
        ),
    )
    authority = SecuredQueryReceiptAuthority(now=lambda: NOW)
    authority.issue(root)
    handler = SecuredTypedPathNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        receipt_authority=authority,
    )
    node = OntologyQueryNode(
        node_id="backends",
        kind=QueryNodeKind.TYPED_PATH,
        depends_on=("gateway",),
        arguments_json=canonical_json(
            {
                "steps": [
                    {
                        "link_type": "routes_to",
                        "direction": "outgoing",
                        "selector": {"kind": "object_type", "name": "Resource"},
                    }
                ],
                "as_of": NOW.isoformat(),
                "purpose": "operations-review",
                "limit": 10,
            }
        ),
        output_kind="query.table",
    )
    result = await handler(
        node,
        {
            "gateway": QueryNodeResult(
                value=QueryTable(
                    rows=(QueryRow.from_values("gateway", {"id": "gateway"}),), complete=True
                ),
                evidence_refs=(
                    f"ontology-object-set-output:{root.receipt.projected_result_digest}",
                ),
            )
        },
    )
    selected = authority.resolve_presentation_read(
        result.evidence_refs,
        invocation_context=FunctionInvocationContext(
            caller_agent="Bragi", caller_role=CeilingRole.READER, purposes=("operations-review",)
        ),
        expected_release=root.receipt.ontology_release,
        expected_purpose="operations-review",
    )
    expected = {"backend"} if has_backend else set()
    assert {obj.id for obj in selected.materialization.graph.objects} == expected
    assert {row.row_id for row in result.value.rows} == expected
    assert selected.receipt.complete is True
    assert selected.receipt.execution_authority is False


def test_default_definition_keeps_the_existing_wire_shape():
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
    )
    assert "object_ids" not in definition.model_dump(mode="json")


def test_explicit_ids_cannot_silently_mix_with_traversal():
    with pytest.raises(ValueError, match="MUST NOT be combined"):
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            object_ids=("backend",),
            root_ids=("gateway",),
            traversal={"link_types": ["routes_to"], "direction": "outgoing", "max_depth": 1},
            as_of=NOW,
            purpose="operations-review",
        )
