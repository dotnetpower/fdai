"""Exact-target Azure semantic current-state function tests."""

from __future__ import annotations

from datetime import UTC, datetime

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
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
    resource_current_state_function_type,
)
from fdai.delivery.azure.semantic_resource_current_state import (
    semantic_resource_current_state_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord
from fdai.shared.providers.state_evidence import STATE_FACT_METADATA_PROPERTY

NOW = datetime(2026, 8, 21, 3, 20, tzinfo=UTC)


def _query_result(
    *,
    source_observed_at: str | None,
    complete: bool = True,
    resource_type: str = "compute.container-app",
    provider_state: dict[str, object] | None = None,
    normalized_status: str | None = None,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=2,
    )
    provider: dict[str, object] = {
        "properties": (
            provider_state
            if provider_state is not None
            else {
                "latestRevisionName": "app-example--new",
                "latestReadyRevisionName": "app-example--ready",
                "provisioningState": "Succeeded",
                "runningStatus": "Running",
            }
        )
    }
    if normalized_status is not None:
        provider["status"] = normalized_status
    if source_observed_at is not None:
        provider[STATE_FACT_METADATA_PROPERTY] = {"effective_at": source_observed_at}
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="scope-example/resource-group/example-rg/app-example",
                    object_type="Resource",
                    properties={
                        "id": "resource-example",
                        "name": "app-example",
                        "type": resource_type,
                        "properties": provider,
                    },
                ),
            ),
            links=(),
            truncated=not complete,
        ),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=(None if complete else ObjectSetTruncationReason.RESULT_LIMIT),
    )
    release = build_ontology_release(function_types=(resource_current_state_function_type(),))
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=1,
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


def _context() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )


async def _invoke(query_result: SecuredObjectSetQueryResult) -> dict[str, object]:
    declaration = resource_current_state_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        semantic_resource_current_state_function(release),
    )
    result = await registry.invoke(
        RESOURCE_CURRENT_STATE_FUNCTION_NAME,
        {"query_result": query_result.model_dump(mode="json")},
        context=_context(),
    )
    assert isinstance(result, dict)
    return result


async def test_current_state_preserves_revision_names_without_ready_inference() -> None:
    result = await _invoke(_query_result(source_observed_at="2026-08-21T03:19:00+00:00"))

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    values = rows[0]["values"]
    assert values["revision_name"] == "app-example--new"
    assert values["ready_revision_name"] == "app-example--ready"
    assert "ready" not in values
    assert values["source_observed_at"] == "2026-08-21T03:19:00+00:00"
    assert values["inventory_read_at"] == NOW.isoformat()
    assert values["execution_authority"] is False


async def test_current_state_retains_values_but_is_incomplete_without_source_time() -> None:
    result = await _invoke(_query_result(source_observed_at=None))

    assert result["complete"] is False
    assert result["truncation_reason"] == "source_observed_at_unavailable"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["revision_name"] == "app-example--new"
    assert rows[0]["values"]["source_observed_at"] is None


async def test_current_state_rejects_incomplete_target_before_projection() -> None:
    result = await _invoke(
        _query_result(
            source_observed_at="2026-08-21T03:19:00+00:00",
            complete=False,
        )
    )

    assert result["complete"] is False
    assert result["rows"] == []
    assert result["truncation_reason"] == "target_resolution_incomplete"


async def test_current_state_reads_the_canonical_state_fact_property() -> None:
    query_result = _query_result(source_observed_at="2026-08-21T03:19:00+00:00")
    provider = query_result.materialization.graph.objects[0].properties["properties"]

    assert isinstance(provider, dict)
    assert STATE_FACT_METADATA_PROPERTY in provider


async def test_a_resource_without_a_revision_concept_reports_no_revision_gap() -> None:
    result = await _invoke(
        _query_result(
            source_observed_at="2026-08-21T03:19:00+00:00",
            resource_type="kubernetes-cluster",
            provider_state={"provisioningState": "Succeeded", "powerState": {"code": "Running"}},
            normalized_status="Running",
        )
    )

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    values = rows[0]["values"]
    assert values["provisioning_status"] == "Succeeded"
    assert values["running_status"] == "Running"
    assert values["target_state_assessment"] == "observed_running"
    assert values["assessment_scope"] == "exact_target_only"
    assert values["related_resources_assessed"] is False
    assert "revision_name" not in values
    assert "ready_revision_name" not in values


async def test_an_unobserved_running_status_stays_a_recorded_gap() -> None:
    result = await _invoke(
        _query_result(
            source_observed_at="2026-08-21T03:19:00+00:00",
            resource_type="kubernetes-cluster",
            provider_state={"provisioningState": "Succeeded"},
        )
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "running_status_unavailable"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["running_status"] is None
    assert rows[0]["values"]["target_state_assessment"] == "observed_not_running"


async def test_no_observed_state_keeps_target_abnormality_unproven() -> None:
    result = await _invoke(
        _query_result(
            source_observed_at="2026-08-21T03:19:00+00:00",
            resource_type="kubernetes-cluster",
            provider_state={},
        )
    )

    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["target_state_assessment"] == "not_proven"
