"""Exact-scope contextual Resource FunctionType tests."""

from datetime import UTC, datetime

import pytest
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
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai_service_contracts import context_selection_digest

NOW = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


def _result(
    objects: tuple[OntologyObjectRecord, ...],
    *,
    links: tuple[OntologyLinkRecord, ...] = (),
) -> SecuredObjectSetQueryResult:
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
        graph=OntologyGraphSnapshot(
            objects=objects,
            links=links,
            truncated=False,
            source_generation="generation-1",
        ),
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
            returned_link_count=len(links),
            complete=True,
            truncated=False,
            source_generation="generation-1",
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
    *,
    generation: str = "generation-1",
    capability: dict[str, object] | None = None,
    include_capability: bool = True,
) -> dict[str, object]:
    declaration = contextual_resource_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(declaration, contextual_resource_function(release))
    identity = {
        "principal_id": "operator",
        "principal_scope_digest": f"sha256:{'a' * 64}",
        "ontology_release_digest": release.digest,
        "source_generation": generation,
        "complete": True,
    }
    selection_digest = context_selection_digest(
        kind="screen",
        screen_id="ontology-instances",
        resource_group_id=None,
        resource_ids=tuple(resource_ids),
        **identity,
    )
    value = await registry.invoke(
        CONTEXTUAL_RESOURCE_FUNCTION_NAME,
        {
            "query_result": result.model_dump(mode="json"),
            "context_kind": "screen",
            "context_id": "ontology-instances",
            "resource_ids": resource_ids,
            **identity,
            "selection_digest": selection_digest,
            **(
                {
                    "selection_capability": capability
                    or {
                        "selection_token": "context-selection:" + "d" * 32,
                        "selection_digest": selection_digest,
                    },
                }
                if include_capability
                else {}
            ),
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


async def test_contextual_function_holds_without_a_valid_opaque_capability() -> None:
    result = await _invoke(
        _result((_resource("resource-a"),)),
        ["resource-a"],
        capability={
            "selection_token": "context-selection:" + "f" * 32,
            "selection_digest": "sha256:" + "e" * 64,
        },
    )

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "context_capability_mismatch",
    }


async def test_contextual_function_requires_an_opaque_capability() -> None:
    with pytest.raises(ValueError, match="input_schema"):
        await _invoke(
            _result((_resource("resource-a"),)),
            ["resource-a"],
            include_capability=False,
        )


async def test_contextual_function_reads_the_complete_512_id_context() -> None:
    resources = tuple(_resource(f"resource-{index}") for index in range(512))
    result = await _invoke(_result(resources), [resource.id for resource in resources])

    assert result["complete"] is True
    assert len(result["rows"]) == 512


async def test_contextual_function_holds_on_scope_widening() -> None:
    result = await _invoke(
        _result((_resource("resource-a"),)),
        ["resource-a", "resource-b"],
    )

    assert result["complete"] is True
    assert [row["values"]["id"] for row in result["rows"]] == ["resource-a"]


async def test_contextual_function_does_not_claim_link_coverage() -> None:
    result = await _invoke(
        _result(
            (_resource("resource-a"), _resource("resource-b")),
            links=(OntologyLinkRecord("depends_on", "resource-a", "resource-b"),),
        ),
        ["resource-a", "resource-b"],
    )

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "context_object_only",
    }


async def test_contextual_function_rejects_an_outside_id() -> None:
    result = await _invoke(
        _result((_resource("resource-outside"),)),
        ["resource-a", "resource-b"],
    )

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "context_scope_mismatch",
    }


async def test_contextual_function_holds_on_source_generation_mismatch() -> None:
    result = await _invoke(
        _result((_resource("resource-a"),)),
        ["resource-a"],
        generation="generation-2",
    )

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "context_generation_mismatch",
    }
