from __future__ import annotations

import pytest

from fdai_deployment_cli.capacity import (
    CapabilityDemand,
    WorkloadEnvelope,
    plan_capacity,
)


def test_capacity_uses_input_output_headroom_and_provider_units() -> None:
    envelope = WorkloadEnvelope(
        requests_per_minute=100,
        input_tokens_per_request=500,
        output_tokens_per_request=200,
        concurrent_requests=10,
        utilization_ceiling=0.70,
        provider_unit_tpm=1_000,
    )
    assert envelope.minimum_tpm == 100_000


def test_shared_deployment_aggregates_demand_and_reserve() -> None:
    demands = (
        CapabilityDemand(
            capability="t1.judge",
            deployment_key="mini",
            required=True,
            envelope=WorkloadEnvelope(10, 100, 100, 2),
        ),
        CapabilityDemand(
            capability="t1.vision",
            deployment_key="mini",
            required=False,
            envelope=WorkloadEnvelope(10, 100, 100, 2),
        ),
    )
    plan = plan_capacity(
        demands,
        available_tpm_by_deployment={"mini": 20_000},
        existing_tpm_by_deployment={"mini": 1_000},
    )
    assert plan[0].required_tpm == 6_000
    assert plan[0].reserve_tpm == 4_000
    assert plan[0].sufficient
    assert plan[0].required_capabilities == ("t1.judge",)


def test_capacity_requires_required_capability_and_quota_evidence() -> None:
    optional = CapabilityDemand(
        capability="optional",
        deployment_key="model",
        required=False,
        envelope=WorkloadEnvelope(1, 1, 1, 1),
    )
    with pytest.raises(ValueError, match="required capability"):
        plan_capacity((optional,), available_tpm_by_deployment={"model": 10_000})
    required = CapabilityDemand(
        capability="t1.judge",
        deployment_key="model",
        required=True,
        envelope=optional.envelope,
    )
    with pytest.raises(ValueError, match="quota evidence"):
        plan_capacity((required,), available_tpm_by_deployment={})


@pytest.mark.parametrize(
    "overrides",
    (
        {"requests_per_minute": True},
        {"utilization_ceiling": True},
        {"quota_reserve": False},
        {"utilization_ceiling": float("nan")},
        {"utilization_ceiling": float("inf")},
        {"quota_reserve": float("nan")},
    ),
)
def test_capacity_rejects_non_numeric_and_non_finite_inputs(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "requests_per_minute": 1,
        "input_tokens_per_request": 1,
        "output_tokens_per_request": 1,
        "concurrent_requests": 1,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        WorkloadEnvelope(**values)  # type: ignore[arg-type]
