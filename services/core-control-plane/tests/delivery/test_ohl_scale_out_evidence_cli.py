"""Contracts for the protected OHL scale-out proposal publisher."""

from __future__ import annotations

import pytest
from fdai.delivery.ohl_scale_out_evidence_cli import (
    OhlScaleOutProposalConfig,
    build_scale_out_proposal,
    publish_scale_out_proposal,
)
from fdai.shared.providers.testing import InMemoryEventBus

_TARGET = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/rg-example/providers/Microsoft.Compute/"
    "virtualMachineScaleSets/vmss-example"
)
_INITIATOR = "00000000-0000-0000-0000-000000000001"


def _config(**overrides: object) -> OhlScaleOutProposalConfig:
    values: dict[str, object] = {
        "bootstrap_servers": "event.example.com:9093",
        "topic": "aw.change.events",
        "target_resource_id": _TARGET,
        "initiator_principal": _INITIATOR,
        "campaign_id": "campaign-20260813",
        "baseline_capacity": 1,
    }
    values.update(overrides)
    return OhlScaleOutProposalConfig(**values)  # type: ignore[arg-type]


def test_proposal_is_retry_stable_and_increases_capacity_by_one() -> None:
    first = build_scale_out_proposal(_config())
    retry = build_scale_out_proposal(_config())

    assert retry == first
    assert first["idempotency_key"] == "ohl-scale-out:campaign-20260813"
    assert first["operator_initiated"] is True
    assert first["action_type"] == "ops.scale-out"
    assert first["resource_id"] == _TARGET
    assert first["params"] == {
        "target_resource_ref": _TARGET,
        "replica_count": 2,
        "reason": "OHL Lane F protected scale-out evidence campaign.",
    }


async def test_publish_uses_target_partition_key_and_primary_topic() -> None:
    config = _config()
    event_bus = InMemoryEventBus()

    receipt = await publish_scale_out_proposal(config, event_bus)
    envelopes = [
        envelope async for envelope in event_bus.subscribe("aw.change.events", "test-reader")
    ]

    assert receipt.topic == "aw.change.events"
    assert len(envelopes) == 1
    assert envelopes[0].key == _TARGET
    assert envelopes[0].payload == build_scale_out_proposal(config)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target_resource_id", "/subscriptions/example/vmss", "Azure VM Scale Set"),
        ("initiator_principal", "not-a-uuid", "MUST be a UUID"),
        ("campaign_id", "unsafe campaign", "safe characters"),
        ("baseline_capacity", 1000, r"MUST be in \[0, 999\]"),
    ],
)
def test_invalid_proposal_coordinates_fail_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _config(**{field: value})


def test_environment_contract_requires_all_coordinates() -> None:
    with pytest.raises(ValueError, match="KAFKA_BOOTSTRAP_SERVERS"):
        OhlScaleOutProposalConfig.from_env({})
