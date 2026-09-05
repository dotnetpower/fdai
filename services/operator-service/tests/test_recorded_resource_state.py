"""Recorded state projection regressions: exact values do not imply health or authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.operations.contracts import InventoryInstanceResource
from fdai_operator_service.families.operations.instance_explorer import _resource_projection
from fdai_operator_service.families.operations.recorded_state import recorded_resource_states

NOW = datetime(2026, 9, 5, 0, 5, tzinfo=UTC)
OBSERVED = "2026-09-05T00:00:00+00:00"


def _metadata(**overrides: object) -> dict[str, object]:
    return {
        "lane": "observed",
        "authority": "provider",
        "source_identity": "inventory-provider",
        "source_revision": "generation-1",
        "effective_at": OBSERVED,
        "recorded_at": OBSERVED,
        "evidence_cutoff": OBSERVED,
        "freshness_ceiling_seconds": 600,
        "completeness": 1.0,
        "synthetic": False,
        "conflicts": [],
        "evidence_refs": ["inventory:generation-1"],
        **overrides,
    }


def _state(properties: Mapping[str, object], axis: str = "operational") -> dict[str, object]:
    result = recorded_resource_states(properties, now=NOW)[axis]
    assert isinstance(result, dict)
    return result


@pytest.mark.parametrize("index", range(29))
def test_all_29_previously_dropped_raw_states_are_retained(index: int) -> None:
    provider = (
        {"runningStatus": "Running", "provisioningState": "Succeeded"}
        if index < 20
        else {"powerState": {"code": "Running"}, "provisioningState": "Succeeded"}
    )
    path = "properties.runningStatus" if index < 20 else "properties.powerState.code"
    projected = _resource_projection(
        InventoryInstanceResource(
            resource_id=f"example-resource-{index:02d}",
            resource_type=(
                "compute.container-app"
                if index < 9
                else "compute.container-app-job"
                if index < 20
                else "kubernetes-node-pool"
            ),
            properties={
                "name": f"example-{index}",
                "subscriptionId": "example-subscription",
                "properties": {**provider, "secret": "private-provider-payload"},
            },
            last_seen=NOW,
        ),
        root_id=None,
        now=NOW,
    )
    states = projected["states"]
    assert isinstance(states, dict)
    assert states["operational"] == {
        "value": "Running",
        "source_path": path,
        "observed_at": None,
        "recorded_at": None,
        "freshness": "unknown",
        "completeness": None,
        "conflicts": [],
        "reason": "state_metadata_not_recorded",
    }
    assert states["provisioning"]["value"] == "Succeeded"
    assert states["availability"]["value"] is None
    assert states["availability"]["reason"] == "state_not_recorded"
    assert projected["status"] == "Succeeded"
    assert projected["subscription_id"] == "example-subscription"
    assert "private-provider-payload" not in repr(projected)


@pytest.mark.parametrize(
    "value", ["Online", "Active", "Enabled", "PowerState/running", " Running "]
)
@pytest.mark.parametrize("path", ["status", "state", "phase", "readiness"])
def test_explicit_operational_values_are_exact_not_collapsed(path: str, value: str) -> None:
    assert _state({path: value})["value"] == value


def test_canonical_resource_wrapper_and_provisioning_are_separate() -> None:
    properties = {
        "properties": {
            "properties": {"powerState": {"code": "Stopped"}, "provisioningState": "Succeeded"}
        }
    }
    assert _state(properties)["value"] == "Stopped"
    assert _state(properties)["source_path"] == "properties.properties.powerState.code"
    assert _state(properties, "provisioning")["value"] == "Succeeded"
    assert _state({"properties": {"provisioningState": "Succeeded"}})["value"] is None
    assert _state({"status": "Running"}, "availability")["value"] is None
    assert (
        _state({"properties": {"availabilityState": "Unavailable"}}, "availability")["value"]
        == "Unavailable"
    )


@pytest.mark.parametrize("value", [None, "", "unknown", "Unknown", " unknown ", {}, True])
def test_missing_and_unknown_values_are_not_supplied_states(value: object) -> None:
    assert _state({"status": value}) == {
        "value": None,
        "source_path": None,
        "observed_at": None,
        "recorded_at": None,
        "freshness": "unknown",
        "completeness": None,
        "conflicts": [],
        "reason": "state_not_recorded",
    }


def test_flat_canonical_metadata_applies_only_to_sibling_status_state() -> None:
    properties = {
        "state": "Online",
        "state_fact_metadata": _metadata(),
        "properties": {"provisioningState": "Succeeded", "availabilityState": "Available"},
    }
    fact = _state(properties)
    assert fact["observed_at"] == OBSERVED
    assert fact["recorded_at"] == OBSERVED
    assert fact["freshness"] == "fresh"
    assert fact["reason"] is None
    for axis in ("provisioning", "availability"):
        assert _state(properties, axis)["observed_at"] is None
        assert _state(properties, axis)["freshness"] == "unknown"


def test_exact_property_metadata_preserves_stale_conflicting_record() -> None:
    properties = {
        "properties": {"runningStatus": "Running"},
        "state_fact_metadata": {
            "properties.runningStatus": _metadata(
                freshness_ceiling_seconds=60,
                completeness=0.5,
                conflicts=["provider-state-disagreement"],
            )
        },
    }
    fact = _state(properties)
    assert fact["value"] == "Running"
    assert fact["observed_at"] == OBSERVED
    assert fact["freshness"] == "stale"
    assert fact["completeness"] == 0.5
    assert fact["conflicts"] == ["provider-state-disagreement"]
    assert fact["reason"] == "state_conflicting"
    assert "verified" not in repr(fact)


def test_staleness_and_incomplete_metadata_do_not_erase_values() -> None:
    stale = _state(
        {"status": "Active", "state_fact_metadata": _metadata(freshness_ceiling_seconds=1)}
    )
    assert stale["value"] == "Active"
    assert stale["reason"] == "state_stale"
    partial = _state({"status": "Active", "state_fact_metadata": {"status": {"completeness": 0}}})
    assert partial["observed_at"] is None
    assert partial["recorded_at"] is None
    assert partial["freshness"] == "unknown"
    assert partial["completeness"] == 0
    assert partial["reason"] == "state_metadata_incomplete"


def test_recent_cutoff_cannot_refresh_an_old_effective_state() -> None:
    fact = _state(
        {
            "state": "Running",
            "state_fact_metadata": _metadata(
                effective_at="2026-09-04T00:00:00+00:00",
                evidence_cutoff=OBSERVED,
                recorded_at=OBSERVED,
            ),
        }
    )
    assert fact["value"] == "Running"
    assert fact["freshness"] == "stale"


@pytest.mark.parametrize(
    "missing", ["effective_at", "recorded_at", "lane", "authority", "synthetic"]
)
def test_missing_observation_metadata_never_becomes_fresh(missing: str) -> None:
    metadata = _metadata()
    metadata.pop(missing)
    fact = _state({"state": "Running", "state_fact_metadata": {"state": metadata}})
    assert fact["value"] == "Running"
    assert fact["freshness"] == "unknown"


def test_impossible_time_order_is_sanitized_before_crossing_the_api() -> None:
    fact = _state(
        {
            "state": "Running",
            "state_fact_metadata": _metadata(
                recorded_at="2026-09-04T00:00:00+00:00",
            ),
        }
    )
    assert fact["value"] == "Running"
    assert fact["observed_at"] is None
    assert fact["recorded_at"] is None
    assert fact["reason"] == "state_metadata_invalid"


def test_mismatched_metadata_property_is_not_reused() -> None:
    fact = _state(
        {
            "properties": {"runningStatus": "Running"},
            "state_fact_metadata": {
                "properties.runningStatus": _metadata(source_path="properties.provisioningState")
            },
        }
    )
    assert fact["observed_at"] is None
    assert fact["freshness"] == "unknown"


@pytest.mark.parametrize(
    "overrides",
    [
        {"effective_at": "2026-09-05"},
        {"effective_at": "2026-09-05T00:00:00"},
        {"effective_at": "2026-99-05T00:00:00Z"},
        {"recorded_at": "x" * 256},
        {"freshness_ceiling_seconds": True},
        {"freshness_ceiling_seconds": -1},
        {"completeness": float("nan")},
        {"completeness": float("inf")},
        {"completeness": True},
        {"completeness": 2},
        {"conflicts": ["x"] * 17},
        {"conflicts": ["x" * 257]},
        {"conflicts": [None]},
        {"lane": "execution"},
        {"authority": "execution_ledger"},
        {"synthetic": "false"},
    ],
)
def test_malformed_metadata_stays_unknown_without_discarding_state(
    overrides: dict[str, object],
) -> None:
    fact = _state({"status": "Enabled", "state_fact_metadata": _metadata(**overrides)})
    assert fact["value"] == "Enabled"
    assert fact["observed_at"] is None
    assert fact["recorded_at"] is None
    assert fact["freshness"] == "unknown"
    assert fact["completeness"] is None
    assert fact["reason"] == "state_metadata_invalid"


def test_future_metadata_is_not_fresh_and_state_strings_are_bounded() -> None:
    fact = _state(
        {
            "status": "Enabled",
            "state_fact_metadata": _metadata(
                effective_at="2026-09-06T00:00:00Z",
                evidence_cutoff="2026-09-06T00:00:00Z",
                recorded_at="2026-09-06T00:00:00Z",
            ),
        }
    )
    assert fact["freshness"] == "unknown"
    assert fact["reason"] == "state_after_cutoff"
    assert _state({"state": "x" * 257})["reason"] == "state_value_invalid"
    assert _state({"state": "Running\nsecret"})["value"] is None
