"""Operational activity contract safety tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_service_contracts import (
    AgentOperationalActivity,
    JsonSchemaContractValidator,
    OperationalActivityKind,
    OperationalActivityStatus,
    OperationalFreshness,
    PackageResourceSchemaRegistry,
)
from pydantic import ValidationError


def _scan(**overrides: object) -> AgentOperationalActivity:
    values: dict[str, object] = {
        "activity_id": "inventory-scan:attempt-1:completed",
        "idempotency_key": "inventory-scan:attempt-1:completed",
        "kind": OperationalActivityKind.INVENTORY_SCAN,
        "status": OperationalActivityStatus.COMPLETED,
        "owner_agent": "Huginn",
        "producer": "inventory-sync-job",
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "source": "azure-resource-graph",
        "freshness": OperationalFreshness.FRESH,
        "evidence_count": 42,
        "duration_ms": 1200,
        "correlation_id": "attempt-1",
    }
    values.update(overrides)
    return AgentOperationalActivity.model_validate(values)


def test_inventory_scan_contract_is_authority_free_and_schema_valid() -> None:
    activity = _scan()
    payload = activity.model_dump(mode="json")

    assert payload["execution_authority"] is False
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "agent-operational-activity",
        payload,
        version="1.0.0",
    )


def test_inventory_scan_rejects_agent_process_impersonation() -> None:
    with pytest.raises(ValidationError, match="Huginn-owned job evidence"):
        _scan(producer="core-control-plane")


def test_current_state_read_rejects_raw_target_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentOperationalActivity.model_validate(
            {
                "activity_id": "current-state:receipt-1:completed",
                "idempotency_key": "current-state:receipt-1:completed",
                "kind": "current-state.read",
                "status": "completed",
                "owner_agent": "Heimdall",
                "producer": "core-control-plane",
                "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
                "source": "provider-read",
                "freshness": "fresh",
                "resource_id": "must-not-cross-boundary",
            }
        )


def test_failed_activity_requires_bounded_reason() -> None:
    with pytest.raises(ValidationError, match="MUST include a reason code"):
        _scan(status="failed", freshness="unavailable")


def test_execution_authority_cannot_be_raised() -> None:
    with pytest.raises(ValidationError):
        _scan(execution_authority=True)


def test_reason_codes_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="MUST NOT contain duplicates"):
        _scan(reason_codes=("partial", "partial"))
