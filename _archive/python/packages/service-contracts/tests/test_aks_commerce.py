from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceMetric,
    AksCommerceProjection,
    AksCommerceSlo,
    AksCommerceStatus,
    AksCommerceWorkload,
)

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _projection(**overrides: object) -> AksCommerceProjection:
    values: dict[str, object] = {
        "assessment_id": f"sha256:{'a' * 64}",
        "service_id": "order-fulfillment",
        "status": AksCommerceStatus.HEALTHY,
        "summary": "Order fulfillment is healthy for the assessed window.",
        "observed_at": NOW,
        "window_start": NOW - timedelta(minutes=5),
        "window_end": NOW,
        "complete": True,
        "synthetic": False,
        "dependency_path": ("storefront", "order-api", "order-queue", "order-processor"),
        "workloads": (
            AksCommerceWorkload(
                workload_id="order-api",
                display_name="Order API",
                resource_ref="resource:order-api",
                ready=True,
                revision="revision-1",
                evidence_state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        "metrics": (
            AksCommerceMetric(
                name="stream.active_messages",
                unit="count",
                current=0,
                previous=0,
                source_ref="source:service-bus",
                observed_at=NOW,
                state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        "slos": (
            AksCommerceSlo(
                slo_id="order-fulfillment.availability",
                objective_ratio=0.99,
                observed_ratio=1,
                budget_remaining_ratio=1,
                breached=False,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:synthetic",
            ),
        ),
        "evidence_refs": ("evidence:one",),
    }
    values.update(overrides)
    return AksCommerceProjection.model_validate(values)


def test_projection_accepts_complete_authority_free_evidence() -> None:
    projection = _projection()

    assert projection.status is AksCommerceStatus.HEALTHY
    assert projection.execution_authority is False
    assert projection.owner_agent == "Forseti"
    assert projection.observer_agent == "Heimdall"


def test_projection_requires_incomplete_evidence_to_be_held() -> None:
    with pytest.raises(ValueError, match="must be held"):
        _projection(complete=False, evidence_gaps=("source_unavailable",))


def test_unqualified_metric_cannot_carry_a_value() -> None:
    with pytest.raises(ValueError, match="cannot carry a value"):
        AksCommerceMetric(
            name="stream.active_messages",
            unit="count",
            current=1,
            source_ref="source:service-bus",
            observed_at=NOW,
            state=AksCommerceEvidenceState.STALE,
        )
