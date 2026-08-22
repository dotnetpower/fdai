"""Verified collection-state FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_MEASURE_CONCEPTS,
    RESOURCE_STATE_MEASURE_TERMS,
    resource_state_function_type,
    resource_state_inventory_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)


def _state_fact(*, observed_at: datetime) -> dict[str, object]:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="generation-example",
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-generation:generation-example",),
    ).to_mapping()


def _resource(
    name: str,
    state: str | None,
    *,
    observed_at: datetime | None = None,
) -> OntologyObjectRecord:
    provider: dict[str, object] = {}
    if state is not None:
        provider["state"] = state
    if observed_at is not None:
        provider[STATE_FACT_METADATA_PROPERTY] = _state_fact(observed_at=observed_at)
    return OntologyObjectRecord(
        id=f"resource-{name}",
        object_type="Resource",
        properties={
            "id": f"resource-{name}",
            "name": name,
            "type": "postgresql-server",
            "properties": provider,
        },
    )


def _query_result(
    objects: tuple[OntologyObjectRecord, ...],
    *,
    complete: bool = True,
) -> SecuredObjectSetQueryResult:
    declaration = resource_state_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=(), truncated=not complete),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
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
            complete=complete,
            truncated=not complete,
            truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
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


async def _invoke(
    query_result: SecuredObjectSetQueryResult,
    *,
    concepts: tuple[str, ...],
) -> dict[str, object]:
    declaration = resource_state_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        resource_state_inventory_function(release),
    )
    result = await registry.invoke(
        RESOURCE_STATE_FUNCTION_NAME,
        {
            "query_result": query_result.model_dump(mode="json"),
            "state_concepts": list(concepts),
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_state_function_declares_canonical_measure_concepts() -> None:
    declaration = resource_state_function_type()

    assert declaration.output_schema["x-fdai-measure-concepts"] == list(
        RESOURCE_STATE_MEASURE_CONCEPTS
    )
    assert declaration.output_schema["x-fdai-measure-value-groups"] == [
        {"concept": concept, "terms": list(RESOURCE_STATE_MEASURE_TERMS[concept])}
        for concept in RESOURCE_STATE_MEASURE_CONCEPTS
    ]


async def test_state_function_returns_only_requested_verified_states() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "PowerState/stopped", observed_at=observed_at),
                _resource("database-b", "Running", observed_at=observed_at),
                _resource("database-c", "Paused", observed_at=observed_at),
            )
        ),
        concepts=("resource_state.stopped",),
    )

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    values = rows[0]["values"]
    assert values["name"] == "database-a"
    assert values["state_concept"] == "resource_state.stopped"
    assert values["source_observed_at"] == observed_at.isoformat()
    assert values["execution_authority"] is False


async def test_state_function_preserves_matches_but_marks_missing_state_incomplete() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (
                _resource("database-a", "Stopped", observed_at=observed_at),
                _resource("database-b", None),
            )
        ),
        concepts=("resource_state.stopped",),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_state_evidence_incomplete"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1


async def test_state_function_rejects_an_incomplete_secured_scope() -> None:
    observed_at = NOW - timedelta(minutes=5)
    result = await _invoke(
        _query_result(
            (_resource("database-a", "Stopped", observed_at=observed_at),),
            complete=False,
        ),
        concepts=("resource_state.stopped",),
    )

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "resource_scope_incomplete",
    }
