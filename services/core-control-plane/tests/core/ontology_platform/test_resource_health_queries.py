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
    ResourceHealthAvailabilityState,
    ResourceHealthCollection,
    ResourceHealthCoverage,
    ResourceHealthCoverageStatus,
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


def _collection(
    resource_ids: tuple[str, ...],
    *,
    observations: tuple[ResourceHealthObservation, ...] = (),
    coverage_statuses: tuple[ResourceHealthCoverageStatus, ...],
) -> ResourceHealthCollection:
    return ResourceHealthCollection(
        resource_ids=resource_ids,
        observations=observations,
        coverage=tuple(
            ResourceHealthCoverage(resource_id=resource_id, status=status)
            for resource_id, status in zip(resource_ids, coverage_statuses, strict=True)
        ),
        started_at=NOW - timedelta(seconds=2),
        completed_at=NOW,
        attempt_ref="azure-resource-health-query:example",
    )


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


def test_health_collection_requires_coverage_for_the_exact_denominator() -> None:
    with pytest.raises(ValueError, match="coverage MUST equal"):
        ResourceHealthCollection(
            resource_ids=("resource-service-a", "resource-service-b"),
            observations=(),
            coverage=(
                ResourceHealthCoverage(
                    resource_id="resource-service-a",
                    status=ResourceHealthCoverageStatus.NO_RECORD,
                ),
            ),
            started_at=NOW,
            completed_at=NOW,
            attempt_ref="azure-resource-health-query:incomplete-denominator",
        )


async def test_health_function_preserves_mixed_health_and_inventory_state() -> None:
    objects = (_resource("service-a", "Stopped"), _resource("service-b", "Running"))
    reader = _Reader(
        _collection(
            ("resource-service-a", "resource-service-b"),
            observations=(
                ResourceHealthObservation(
                    resource_id="resource-service-a",
                    availability_state=ResourceHealthAvailabilityState.UNAVAILABLE,
                    reason_kind="platform_initiated",
                    provider_observed_at=NOW - timedelta(minutes=3),
                    evidence_ref="azure-resource-health:service-a",
                ),
                ResourceHealthObservation(
                    resource_id="resource-service-b",
                    availability_state=ResourceHealthAvailabilityState.AVAILABLE,
                    reason_kind="status_only",
                    provider_observed_at=NOW - timedelta(minutes=3),
                    evidence_ref="azure-resource-health:service-b",
                ),
            ),
            coverage_statuses=(
                ResourceHealthCoverageStatus.OBSERVED,
                ResourceHealthCoverageStatus.OBSERVED,
            ),
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
        "resource_health",
        "current_inventory",
    ]
    assert rows[0]["values"]["health_concept"] == "resource_health.not_ready"
    assert rows[0]["values"]["health_kind"] == "platform_initiated"
    assert rows[0]["values"]["availability_state"] == "unavailable"
    assert rows[0]["values"]["coverage_state"] == "observed"
    assert rows[0]["values"]["collection_started_at"] == "2026-08-21T13:59:58+00:00"
    assert rows[0]["values"]["collection_completed_at"] == NOW.isoformat()
    assert "availability_state" not in rows[1]["values"] or (
        rows[1]["values"]["availability_state"] is None
    )
    assert all(row["values"]["execution_authority"] is False for row in rows)
    assert reader.calls == [("resource-service-a", "resource-service-b")]


async def test_health_function_preserves_every_overlapping_requested_concept() -> None:
    objects = (_resource("service-a", "Running"),)
    reader = _Reader(
        _collection(
            ("resource-service-a",),
            observations=(
                ResourceHealthObservation(
                    resource_id="resource-service-a",
                    availability_state=ResourceHealthAvailabilityState.DEGRADED,
                    reason_kind="platform_initiated",
                    provider_observed_at=NOW - timedelta(minutes=1),
                    evidence_ref="azure-resource-health:service-a",
                ),
            ),
            coverage_statuses=(ResourceHealthCoverageStatus.OBSERVED,),
        )
    )

    result = await _invoke(
        reader,
        _query_result(objects),
        health_concepts=("resource_health.not_ready", "resource_health.unhealthy"),
    )

    values = result["rows"][0]["values"]
    assert values["health_concept"] == "resource_health.not_ready"
    assert values["matching_health_concepts"] == [
        "resource_health.not_ready",
        "resource_health.unhealthy",
    ]


async def test_health_function_keeps_matches_but_demotes_partial_provider_coverage() -> None:
    objects = (_resource("service-a", "Running"), _resource("service-b", "Running"))
    reader = _Reader(
        _collection(
            ("resource-service-a", "resource-service-b"),
            observations=(
                ResourceHealthObservation(
                    resource_id="resource-service-a",
                    availability_state=ResourceHealthAvailabilityState.DEGRADED,
                    reason_kind="platform_initiated",
                    provider_observed_at=NOW - timedelta(minutes=2),
                    evidence_ref="azure-resource-health:service-a",
                ),
            ),
            coverage_statuses=(
                ResourceHealthCoverageStatus.OBSERVED,
                ResourceHealthCoverageStatus.NO_RECORD,
            ),
        )
    )

    result = await _invoke(reader, _query_result(objects))

    assert result["complete"] is False
    assert result["truncation_reason"] == "no_record"
    assert len(result["rows"]) == 2
    assert result["rows"][1]["values"]["coverage_state"] == "no_record"


async def test_health_function_rejects_provider_scope_widening() -> None:
    objects = (_resource("service-a", "Running"),)
    reader = _Reader(
        _collection(
            ("resource-other",),
            coverage_statuses=(ResourceHealthCoverageStatus.NO_RECORD,),
        )
    )

    with pytest.raises(ValueError, match="changed the secured resource scope"):
        await _invoke(reader, _query_result(objects))


async def test_health_function_preserves_unknown_separately_from_provisioning_state() -> None:
    objects = (_resource("service-a", "Running"),)
    reader = _Reader(
        _collection(
            ("resource-service-a",),
            observations=(
                ResourceHealthObservation(
                    resource_id="resource-service-a",
                    availability_state=ResourceHealthAvailabilityState.UNKNOWN,
                    reason_kind="status_only",
                    provider_observed_at=NOW - timedelta(minutes=1),
                    evidence_ref="azure-resource-health:service-a",
                ),
            ),
            coverage_statuses=(ResourceHealthCoverageStatus.OBSERVED,),
        )
    )

    result = await _invoke(
        reader,
        _query_result(objects),
        state_concepts=("resource_state.running",),
    )

    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["availability_state"] == "unknown"
    assert rows[0]["values"]["coverage_state"] == "observed"
    assert rows[1]["values"]["observed_state"] == "Running"
    assert rows[1]["values"]["evidence_family"] == "current_inventory"
    assert all(row["values"]["execution_authority"] is False for row in rows)


async def test_health_function_keeps_non_observation_coverage_reasons_disjoint() -> None:
    objects = (
        _resource("service-a", "Running"),
        _resource("service-b", "Running"),
        _resource("service-c", "Running"),
    )
    resource_ids = tuple(item.id for item in objects)
    reader = _Reader(
        _collection(
            resource_ids,
            coverage_statuses=(
                ResourceHealthCoverageStatus.NOT_MODELED,
                ResourceHealthCoverageStatus.MODELING_UNKNOWN,
                ResourceHealthCoverageStatus.SCOPE_UNREADABLE,
            ),
        )
    )

    result = await _invoke(reader, _query_result(objects))

    assert result["complete"] is False
    assert result["truncation_reason"] == "not_modeled+modeling_unknown+scope_unreadable"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert [row["values"]["coverage_state"] for row in rows] == [
        "not_modeled",
        "modeling_unknown",
        "scope_unreadable",
    ]
    assert all(row["values"]["availability_state"] is None for row in rows)
    assert all(row["values"]["execution_authority"] is False for row in rows)


async def test_health_function_bounds_combined_health_and_inventory_rows() -> None:
    objects = tuple(_resource(f"service-{index:03d}", "Running") for index in range(501))
    resource_ids = tuple(item.id for item in objects)
    observations = tuple(
        ResourceHealthObservation(
            resource_id=resource_id,
            availability_state=ResourceHealthAvailabilityState.UNKNOWN,
            reason_kind="status_only",
            provider_observed_at=NOW - timedelta(minutes=1),
            evidence_ref=f"azure-resource-health:service-{index:03d}",
        )
        for index, resource_id in enumerate(resource_ids)
    )
    reader = _Reader(
        _collection(
            resource_ids,
            observations=observations,
            coverage_statuses=(ResourceHealthCoverageStatus.OBSERVED,) * len(resource_ids),
        )
    )

    result = await _invoke(
        reader,
        _query_result(objects),
        state_concepts=("resource_state.running",),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_health_row_limit"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1000
    assert all(
        row["values"]["execution_authority"] is False for row in rows if isinstance(row, dict)
    )
