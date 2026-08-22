"""Verified Resource Health collection FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
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
from fdai.core.ontology_platform.resource_health_queries import (
    RESOURCE_HEALTH_FUNCTION_NAME,
    ResourceHealthCollection,
    ResourceHealthObservation,
    resource_health_function_type,
    resource_health_inventory_function,
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

NOW = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
HEALTH_GROUPS = {
    "resource_health.not_ready": ("failed", "degraded", "unavailable"),
    "resource_health.unhealthy": ("failed", "degraded", "unavailable", "unknown"),
}


def _resource(name: str, state: str) -> OntologyObjectRecord:
    observed_at = NOW - timedelta(minutes=5)
    state_fact = StateFactMetadata(
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
    )
    return OntologyObjectRecord(
        id=f"resource-{name}",
        object_type="Resource",
        properties={
            "id": f"resource-{name}",
            "name": name,
            "type": "app-service",
            "properties": {
                "state": state,
                STATE_FACT_METADATA_PROPERTY: state_fact.to_mapping(),
            },
        },
    )


def _query_result(objects: tuple[OntologyObjectRecord, ...]) -> SecuredObjectSetQueryResult:
    declaration = resource_health_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=64,
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


class _Reader:
    def __init__(self, result: ResourceHealthCollection) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    async def read_current(self, *, resource_ids: tuple[str, ...]) -> ResourceHealthCollection:
        self.calls.append(resource_ids)
        return self.result


async def _invoke(
    reader: _Reader,
    query_result: SecuredObjectSetQueryResult,
    *,
    health_concepts: tuple[str, ...] = ("resource_health.not_ready",),
    state_concepts: tuple[str, ...] = (),
) -> dict[str, object]:
    declaration = resource_health_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        resource_health_inventory_function(
            release,
            reader=reader,
            health_state_values=HEALTH_GROUPS,
        ),
    )
    result = await registry.invoke(
        RESOURCE_HEALTH_FUNCTION_NAME,
        {
            "query_result": query_result.model_dump(mode="json"),
            "health_concepts": list(health_concepts),
            "state_concepts": list(state_concepts),
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_health_function_declares_no_caller_provider_scope_or_authority() -> None:
    declaration = resource_health_function_type()

    assert declaration.name == RESOURCE_HEALTH_FUNCTION_NAME
    assert set(declaration.input_schema["properties"]) == {
        "query_result",
        "health_concepts",
        "state_concepts",
    }
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_health_function_preserves_mixed_health_and_inventory_state() -> None:
    objects = (_resource("service-a", "Stopped"), _resource("service-b", "Running"))
    reader = _Reader(
        ResourceHealthCollection(
            resource_ids=("resource-service-a", "resource-service-b"),
            observations=(
                ResourceHealthObservation(
                    resource_id="resource-service-a",
                    availability_state="Unavailable",
                    reason_kind="platform_initiated",
                    observed_at=NOW - timedelta(minutes=3),
                    evidence_ref="azure-resource-health:service-a",
                ),
                ResourceHealthObservation(
                    resource_id="resource-service-b",
                    availability_state="Available",
                    reason_kind="status_only",
                    observed_at=NOW - timedelta(minutes=3),
                    evidence_ref="azure-resource-health:service-b",
                ),
            ),
            observed_at=NOW,
            complete=True,
            limitation=None,
            attempt_ref="azure-resource-health-query:example",
        )
    )

    result = await _invoke(
        reader,
        _query_result(objects),
        state_concepts=("resource_state.stopped",),
    )

    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    assert [row["values"]["evidence_family"] for row in rows] == [
        "current_inventory",
        "resource_health",
    ]
    assert rows[1]["values"]["health_concept"] == "resource_health.not_ready"
    assert rows[1]["values"]["health_kind"] == "platform_initiated"
    assert all(row["values"]["execution_authority"] is False for row in rows)
    assert reader.calls == [("resource-service-a", "resource-service-b")]


async def test_health_function_keeps_matches_but_demotes_partial_provider_coverage() -> None:
    objects = (_resource("service-a", "Running"), _resource("service-b", "Running"))
    reader = _Reader(
        ResourceHealthCollection(
            resource_ids=("resource-service-a", "resource-service-b"),
            observations=(
                ResourceHealthObservation(
                    resource_id="resource-service-a",
                    availability_state="Degraded",
                    reason_kind="platform_initiated",
                    observed_at=NOW - timedelta(minutes=2),
                    evidence_ref="azure-resource-health:service-a",
                ),
            ),
            observed_at=NOW,
            complete=False,
            limitation="resource_health_coverage_incomplete",
            attempt_ref="azure-resource-health-query:partial",
        )
    )

    result = await _invoke(reader, _query_result(objects))

    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_health_coverage_incomplete"
    assert len(result["rows"]) == 1


async def test_health_function_rejects_provider_scope_widening() -> None:
    objects = (_resource("service-a", "Running"),)
    reader = _Reader(
        ResourceHealthCollection(
            resource_ids=("resource-other",),
            observations=(),
            observed_at=NOW,
            complete=True,
            limitation=None,
            attempt_ref="azure-resource-health-query:wrong-scope",
        )
    )

    with pytest.raises(ValueError, match="changed the secured resource scope"):
        await _invoke(reader, _query_result(objects))
