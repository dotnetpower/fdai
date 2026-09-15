"""Presentation and authority invariants for operational activity schema 1.3."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_service_contracts import (
    AgentOperationalActivity,
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from pydantic import ValidationError


def _scan(**overrides: object) -> AgentOperationalActivity:
    values: dict[str, object] = {
        "schema_version": "1.3.0",
        "activity_id": "inventory.scan:attempt-1:completed",
        "activity_instance_id": "inventory.scan:attempt-1",
        "idempotency_key": "inventory.scan:attempt-1:completed",
        "kind": "inventory.scan",
        "status": "completed",
        "owner_agent": "Huginn",
        "producer": "inventory-sync-job",
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "source": "azure-resource-graph",
        "freshness": "fresh",
        "evidence_count": 0,
        "duration_ms": 10,
        "correlation_id": "attempt-1",
        "summary_key": "inventory_collection",
        "scope_class": "configured-estate",
        "result_state": "measured",
        "result_count": 0,
        "result_unit": "evidence-items",
        "source_cutoff": datetime(2026, 1, 1, tzinfo=UTC),
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "completed_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return AgentOperationalActivity.model_validate(values)


def test_measured_zero_is_schema_valid_and_distinct_from_missing() -> None:
    activity = _scan()
    payload = activity.model_dump(mode="json")

    assert payload["result_state"] == "measured"
    assert payload["result_count"] == 0
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "agent-operational-activity",
        payload,
        version="1.3.0",
    )


def test_unavailable_result_rejects_ambiguous_zero_unit() -> None:
    with pytest.raises(ValidationError, match="unmeasured result MUST NOT include"):
        _scan(
            status="failed",
            freshness="unavailable",
            reason_codes=("provider_failure",),
            result_state="unavailable",
        )


def test_lifecycle_and_summary_classification_cannot_be_forged() -> None:
    with pytest.raises(ValidationError, match="classification MUST match"):
        _scan(
            summary_key="current_state_observation",
            scope_class="investigation",
        )
    with pytest.raises(ValidationError, match="started activity result MUST be not-recorded"):
        _scan(
            status="started",
            completed_at=None,
            result_state="unavailable",
            result_count=None,
            result_unit=None,
        )


def test_json_schema_rejects_forged_observation_owner() -> None:
    activity = AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id="observation:resource-health:campaign-1:completed",
        activity_instance_id="observation:resource-health:campaign-1",
        idempotency_key="observation:resource-health:campaign-1:completed",
        kind="observation",
        status="completed",
        owner_agent="Heimdall",
        producer="observation-campaign-job",
        observation_domain="resource-health",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="resource-health",
        freshness="fresh",
        evidence_count=0,
        summary_key="source_observation",
        scope_class="source-domain",
        result_state="measured",
        result_count=0,
        result_unit="records",
    )
    payload = activity.model_dump(mode="json")
    payload["owner_agent"] = "Njord"

    with pytest.raises(ContractValidationError):
        JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
            "agent-operational-activity",
            payload,
            version="1.3.0",
        )


def test_reason_codes_are_machine_safe_for_every_kind() -> None:
    with pytest.raises(ValidationError, match="machine-safe identifiers"):
        _scan(reason_codes=("provider /subscriptions/example failed",))
