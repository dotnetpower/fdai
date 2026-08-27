"""Exact-scope contextual Resource FunctionType tests."""

from datetime import UTC, datetime

from fdai.core.ontology_platform.contextual_resource_queries import (
    CONTEXTUAL_RESOURCE_FUNCTION_NAME,
    contextual_resource_function,
    contextual_resource_function_type,
)
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
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
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


def _result(objects: tuple[OntologyObjectRecord, ...]) -> SecuredObjectSetQueryResult:
    declaration = contextual_resource_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=(), truncated=False),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=len(objects),
            returned_link_count=0,
            complete=True,
            truncated=False,
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
        ),
    )


def _resource(resource_id: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={"id": resource_id, "name": resource_id, "type": "resource-group"},
    )


async def _invoke(
    result: SecuredObjectSetQueryResult,
    resource_ids: list[str],
) -> dict[str, object]:
    declaration = contextual_resource_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(declaration, contextual_resource_function(release))
    value = await registry.invoke(
        CONTEXTUAL_RESOURCE_FUNCTION_NAME,
        {
            "query_result": result.model_dump(mode="json"),
            "context_kind": "screen",
            "context_id": "ontology-instances",
            "resource_ids": resource_ids,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(value, dict)
    return value


async def test_contextual_function_returns_only_exact_context_membership() -> None:
    result = await _invoke(_result((_resource("resource-a"),)), ["resource-a"])

    assert result["complete"] is True
    assert [row["values"]["id"] for row in result["rows"]] == ["resource-a"]


async def test_contextual_function_holds_on_scope_widening() -> None:
    result = await _invoke(
        _result((_resource("resource-a"), _resource("resource-b"))),
        ["resource-a"],
    )

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "context_scope_mismatch",
    }
