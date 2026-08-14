"""Focused contracts for secured instance relationship projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.instance_relationships import (
    evaluate_instance_relationships,
    instance_relationships_function,
    instance_relationships_function_type,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

_OBSERVED_AT = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)


def _secured_result(
    *,
    links: tuple[OntologyLinkRecord, ...],
    complete: bool = True,
    ontology_release: OntologyRelease | None = None,
) -> SecuredObjectSetQueryResult:
    objects = tuple(
        OntologyObjectRecord(
            id=object_id,
            object_type=object_type,
            properties={"id": object_id},
        )
        for object_id, object_type in (
            ("workload-a", "Workload"),
            ("resource-a", "Resource"),
            ("resource-b", "Resource"),
        )
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.INTERFACE, name="Identifiable"),
        as_of=_OBSERVED_AT,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=links, truncated=not complete),
        concrete_types=("Resource", "Workload"),
        truncated=not complete,
        truncation_reason=("result_limit" if not complete else None),
    )
    receipt = SecuredObjectSetQueryReceipt(
        ontology_release=(ontology_release or build_ontology_release()).ref(),
        projected_result_digest=_projected_result_digest(materialization),
        purpose=definition.purpose,
        caller_role="reader",
        observation_cutoff=_OBSERVED_AT,
        as_of_skew_seconds=0,
        returned_object_count=len(objects),
        returned_link_count=len(links),
        complete=complete,
        truncated=not complete,
        truncation_reason=("result_limit" if not complete else None),
        redactions=ObjectSetRedactionSummary(
            objects_with_redactions=0,
            redacted_identity_count=0,
            access_scope_count=0,
            purpose_binding_count=0,
            undeclared_property_count=0,
            links_with_redactions=0,
            redacted_link_property_count=0,
            removed_link_count=0,
        ),
    )
    return SecuredObjectSetQueryResult(materialization=materialization, receipt=receipt)


def _link(link_type: str, from_id: str, to_id: str) -> OntologyLinkRecord:
    return OntologyLinkRecord(
        link_type=link_type,
        from_id=from_id,
        to_id=to_id,
        properties={},
    )


class _ReceiptVerifier:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid

    def verify(self, **_kwargs: Any) -> bool:
        return self.valid


def _release() -> OntologyRelease:
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
    return build_ontology_release(
        object_types=(resource,),
        link_types=(routes_to,),
        function_types=(instance_relationships_function_type(),),
    )


def test_filters_exact_link_types_and_preserves_stored_direction() -> None:
    secured = _secured_result(
        links=(
            _link("workload_runs_on", "workload-a", "resource-a"),
            _link("routes_to", "resource-a", "resource-b"),
        )
    )

    result = evaluate_instance_relationships(
        secured,
        link_types=("workload_runs_on",),
        limit=100,
    )

    assert result.complete is True
    assert result.truncation_reasons == ()
    assert [row.model_dump() for row in result.relationships] == [
        {
            "link_type": "workload_runs_on",
            "from_id": "workload-a",
            "from_type": "Workload",
            "to_id": "resource-a",
            "to_type": "Resource",
        }
    ]
    assert result.execution_authority is False


def test_empty_result_is_closed_only_for_complete_source() -> None:
    complete = evaluate_instance_relationships(
        _secured_result(links=()),
        link_types=("contains",),
        limit=100,
    )
    incomplete = evaluate_instance_relationships(
        _secured_result(links=(), complete=False),
        link_types=("contains",),
        limit=100,
    )

    assert complete.complete is True
    assert incomplete.complete is False
    assert incomplete.truncation_reasons == ("result_limit",)


def test_relationship_limit_marks_result_incomplete() -> None:
    result = evaluate_instance_relationships(
        _secured_result(
            links=(
                _link("routes_to", "resource-a", "resource-b"),
                _link("routes_to", "resource-b", "resource-a"),
            )
        ),
        link_types=("routes_to",),
        limit=1,
    )

    assert len(result.relationships) == 1
    assert result.complete is False
    assert result.truncation_reasons == ("relationship_limit",)


def test_rejects_secured_graph_with_missing_link_endpoint() -> None:
    with pytest.raises(ValueError, match="link has a missing endpoint"):
        evaluate_instance_relationships(
            _secured_result(links=(_link("routes_to", "resource-a", "missing"),)),
            link_types=("routes_to",),
            limit=100,
        )


def test_function_binding_rejects_link_type_absent_from_release() -> None:
    with pytest.raises(KeyError, match="has no link declaration 'contains'"):
        instance_relationships_function(
            _release(),
            known_link_types=("contains",),
            receipt_verifier=_ReceiptVerifier(valid=True),
            verification_context=object(),
        )


async def test_contextual_function_rejects_unverified_receipt() -> None:
    release = _release()
    secured = _secured_result(
        links=(_link("routes_to", "resource-a", "resource-b"),),
        ontology_release=release,
    )
    verification_context = object()
    function = instance_relationships_function(
        release,
        known_link_types=("routes_to",),
        receipt_verifier=_ReceiptVerifier(valid=False),
        verification_context=verification_context,
    )

    with pytest.raises(PermissionError, match="receipt verification failed"):
        await function(
            {
                "query_result": secured.model_dump(mode="json"),
                "link_types": ["routes_to"],
                "limit": 100,
            },
            FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role="reader",
                purposes=("operations-review",),
                evidence_refs=(secured.receipt.projected_result_digest,),
            ),
        )
