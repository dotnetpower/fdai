"""Server-scoped Service Health FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_ALL_MEASURE_CONCEPTS,
    SERVICE_HEALTH_FUNCTION_NAME,
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


async def _invoke(
    reader: _Reader,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    declaration = service_health_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        service_health_function(release, reader=reader),
    )
    result = await registry.invoke(
        SERVICE_HEALTH_FUNCTION_NAME,
        arguments or {},
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_service_health_function_accepts_only_reviewed_event_type_filters() -> None:
    declaration = service_health_function_type()

    assert set(declaration.input_schema["properties"]) == {"event_types"}
    assert declaration.output_schema["x-fdai-measure-concepts"] == list(
        SERVICE_HEALTH_ALL_MEASURE_CONCEPTS
    )
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_service_health_function_projects_active_event_and_impact() -> None:
    reader = _Reader(
        _collection(
            observations=(
                ServiceHealthObservation(
                    event_id="service-health-event:event-a",
                    event_type="service_issue",
                    title="Regional connectivity issue",
                    level="warning",
                    status="active",
                    impact_start_at=NOW - timedelta(minutes=10),
                    observed_at=NOW,
                    impacted_resource_count=1,
                    impacted_resource_ref="resource:sha256:" + ("a" * 64),
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
        "active_event_count": 1,
        "attempt_ref": "azure-service-health:attempt",
        "count_posture": "exact",
        "execution_authority": False,
        "impacted_resource_count": 1,
        "observed_at": NOW.isoformat(),
        "record_kind": "summary",
        "scope_kind": "subscription",
    }
    assert rows[1]["values"] == {
        "event_id": "service-health-event:event-a",
        "event_evidence_ref": "azure-service-health:event-a",
        "event_type": "service_issue",
        "execution_authority": False,
        "impact_evidence_ref": "azure-service-health-impact:resource-a",
        "impact_start_at": (NOW - timedelta(minutes=10)).isoformat(),
        "impact_status": "active",
        "impacted_resource_count": 1,
        "impacted_resource_ref": "resource:sha256:" + ("a" * 64),
        "level": "warning",
        "observed_at": NOW.isoformat(),
        "region": "example-region",
        "resource_group": "example-rg",
        "resource_name": "service-a",
        "resource_type": "microsoft.app/containerapps",
        "record_kind": "event",
        "scope_kind": "subscription",
        "status": "active",
        "title": "Regional connectivity issue",
    }
    assert reader.calls == 1


async def test_service_health_function_filters_event_types_before_summary() -> None:
    observations = tuple(
        ServiceHealthObservation(
            event_id=f"service-health-event:{event_type}",
            event_type=event_type,
            title=event_type,
            level="warning",
            status="active",
            impact_start_at=NOW - timedelta(minutes=10),
            observed_at=NOW,
            impacted_resource_count=0,
            impacted_resource_ref=None,
            resource_name=None,
            resource_type=None,
            resource_group=None,
            region=None,
            impact_status=None,
            event_evidence_ref=f"azure-service-health:{event_type}",
            impact_evidence_ref=None,
        )
        for event_type in sorted(("service_issue", "planned_maintenance", "health_advisory"))
    )
    result = await _invoke(
        _Reader(_collection(observations=observations)),
        {"event_types": ["service_issue"]},
    )

    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["active_event_count"] == 1
    assert [row["values"]["event_type"] for row in rows[1:]] == ["service_issue"]


async def test_service_health_function_distinguishes_zero_from_unavailable() -> None:
    verified_reader = _Reader(_collection())
    unavailable_reader = _Reader(_collection(complete=False, limitation="source_unavailable"))

    verified = await _invoke(verified_reader)
    unavailable = await _invoke(unavailable_reader)

    assert verified == {
        "complete": True,
        "rows": [
            {
                "row_id": "service-health-summary",
                "values": {
                    "active_event_count": 0,
                    "attempt_ref": "azure-service-health:attempt",
                    "count_posture": "exact",
                    "execution_authority": False,
                    "impacted_resource_count": 0,
                    "observed_at": NOW.isoformat(),
                    "record_kind": "summary",
                    "scope_kind": "subscription",
                },
            }
        ],
        "truncation_reason": None,
    }
    assert unavailable == {
        "complete": False,
        "rows": [
            {
                "row_id": "service-health-summary",
                "values": {
                    "active_event_count": None,
                    "attempt_ref": "azure-service-health:attempt",
                    "count_posture": "unknown",
                    "execution_authority": False,
                    "impacted_resource_count": None,
                    "observed_at": NOW.isoformat(),
                    "record_kind": "summary",
                    "scope_kind": "subscription",
                },
            }
        ],
        "truncation_reason": "source_unavailable",
    }


async def test_service_health_summary_reserves_one_row_at_the_output_limit() -> None:
    observations = tuple(
        ServiceHealthObservation(
            event_id=f"service-health-event:{index:03d}",
            event_type="service_issue",
            title=f"Service issue {index:03d}",
            level="warning",
            status="active",
            impact_start_at=NOW - timedelta(minutes=10) + timedelta(seconds=index),
            observed_at=NOW,
            impacted_resource_count=0,
            impacted_resource_ref=None,
            resource_name=None,
            resource_type=None,
            resource_group=None,
            region=None,
            impact_status=None,
            event_evidence_ref=f"azure-service-health:event-{index:03d}",
            impact_evidence_ref=None,
        )
        for index in range(255)
    )

    result = await _invoke(_Reader(_collection(observations=observations)))

    assert result["complete"] is True
    assert len(result["rows"]) == 256
    assert result["rows"][0]["values"]["active_event_count"] == 255
    assert result["rows"][0]["values"]["count_posture"] == "exact"
