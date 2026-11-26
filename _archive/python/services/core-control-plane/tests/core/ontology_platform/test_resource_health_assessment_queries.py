"""Exact-target health evidence assessment tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_health_assessment_queries import (
    TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
    target_health_assessment_function,
    target_health_assessment_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 8, 21, 0, 10, tzinfo=UTC)


def _table(values: dict[str, object] | None = None) -> dict[str, object]:
    table = QueryTable(
        rows=(QueryRow.from_values("row", values),) if values is not None else (),
        complete=True,
    )
    return json.loads(table.canonical_json())


def _window(concept_id: str, values: tuple[float, ...]) -> dict[str, object]:
    return {
        "concept_id": concept_id,
        "resource_id": "resource-a",
        "unit": "count" if concept_id.startswith("request.") else "nanocores",
        "start": "2026-08-20T23:40:00Z",
        "end": "2026-08-21T00:10:00Z",
        "samples": [
            {"timestamp": f"2026-08-21T00:0{index}:00Z", "value": value}
            for index, value in enumerate(values)
        ],
        "complete": True,
        "evidence_refs": [f"metric:{concept_id}"],
        "missing_reason": None,
    }


async def test_health_assessment_refuses_full_health_from_lifecycle_and_zero_requests() -> None:
    declaration = target_health_assessment_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(declaration, target_health_assessment_function(release))

    result = await registry.invoke(
        TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
        {
            "current_state": _table(
                {
                    "name": "app-example",
                    "provisioning_status": "Succeeded",
                    "running_status": "Running",
                    "source_observed_at": "2026-08-21T00:09:00Z",
                    "inventory_read_at": "2026-08-21T00:10:00Z",
                }
            ),
            "activity": _table(),
            "resource_saturation": _window("resource.saturation", (10.0, 20.0)),
            "request_volume": _window("request.volume", (0.0,)),
            "request_errors": _window("request.errors", (0.0,)),
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert isinstance(result, dict)
    assert result["complete"] is False
    assert result["truncation_reason"] == "health_claim_evidence_incomplete"
    rows = result["rows"]
    assert isinstance(rows, list)
    values = rows[0]["values"]
    assert values["overall_assessment"] == "insufficient_evidence"
    assert values["evidence_sufficient"] is False
    assert values["platform_lifecycle"] == "observed_running"
    assert values["readiness"] == "not_proven"
    assert values["application_service_health"] == "not_proven"
    assert values["request_telemetry"] == "zero_observed_requests_not_health_proof"
    assert values["cpu_average_nanocores"] == 15.0
    assert values["cpu_max_nanocores"] == 20.0
    assert "process_restart_count_unavailable" in values["evidence_gaps"]
    assert "memory_metric_unavailable" in values["evidence_gaps"]
    assert "runtime_logs_unavailable" in values["evidence_gaps"]
    assert values["execution_authority"] is False
