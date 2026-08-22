"""Server-scoped Service Health FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_FUNCTION_NAME,
    SERVICE_HEALTH_MEASURE_CONCEPTS,
    ServiceHealthCollection,
    ServiceHealthObservation,
    service_health_function,
    service_health_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)


class _Reader:
    def __init__(self, result: ServiceHealthCollection) -> None:
        self.result = result
        self.calls = 0

    async def read_active(self) -> ServiceHealthCollection:
        self.calls += 1
        return self.result


def _collection(
    *,
    observations: tuple[ServiceHealthObservation, ...] = (),
    complete: bool = True,
    limitation: str | None = None,
) -> ServiceHealthCollection:
    return ServiceHealthCollection(
        observations=observations,
        observed_at=NOW,
        complete=complete,
        limitation=limitation,
        attempt_ref="azure-service-health:attempt",
    )


async def _invoke(reader: _Reader) -> dict[str, object]:
    declaration = service_health_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        service_health_function(release, reader=reader),
    )
    result = await registry.invoke(
        SERVICE_HEALTH_FUNCTION_NAME,
        {},
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_service_health_function_accepts_no_caller_scope_or_query() -> None:
    declaration = service_health_function_type()

    assert declaration.input_schema["properties"] == {}
    assert declaration.output_schema["x-fdai-measure-concepts"] == list(
        SERVICE_HEALTH_MEASURE_CONCEPTS
    )
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_service_health_function_projects_active_event_and_impact() -> None:
    reader = _Reader(
        _collection(
            observations=(
                ServiceHealthObservation(
                    event_type="service_issue",
                    title="Regional connectivity issue",
                    level="warning",
                    status="active",
                    impact_start_at=NOW - timedelta(minutes=10),
                    observed_at=NOW,
                    impacted_resource_count=1,
                    resource_name="service-a",
                    resource_type="microsoft.app/containerapps",
                    resource_group="example-rg",
                    region="example-region",
                    impact_status="active",
                    event_evidence_ref="azure-service-health:event-a",
                    impact_evidence_ref="azure-service-health-impact:resource-a",
                ),
            )
        )
    )

    result = await _invoke(reader)

    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"] == {
        "event_evidence_ref": "azure-service-health:event-a",
        "event_type": "service_issue",
        "execution_authority": False,
        "impact_evidence_ref": "azure-service-health-impact:resource-a",
        "impact_start_at": (NOW - timedelta(minutes=10)).isoformat(),
        "impact_status": "active",
        "impacted_resource_count": 1,
        "level": "warning",
        "observed_at": NOW.isoformat(),
        "region": "example-region",
        "resource_group": "example-rg",
        "resource_name": "service-a",
        "resource_type": "microsoft.app/containerapps",
        "scope_kind": "subscription",
        "status": "active",
        "title": "Regional connectivity issue",
    }
    assert reader.calls == 1


async def test_service_health_function_distinguishes_zero_from_unavailable() -> None:
    verified_reader = _Reader(_collection())
    unavailable_reader = _Reader(_collection(complete=False, limitation="source_unavailable"))

    verified = await _invoke(verified_reader)
    unavailable = await _invoke(unavailable_reader)

    assert verified == {"complete": True, "rows": [], "truncation_reason": None}
    assert unavailable == {
        "complete": False,
        "rows": [],
        "truncation_reason": "source_unavailable",
    }
