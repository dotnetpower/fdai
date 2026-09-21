"""Recorded state projection regressions: exact values do not imply health or authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai_operator_service.families.operations.contracts import InventoryInstanceResource
from fdai_operator_service.families.operations.instance_explorer import _resource_projection
from fdai_operator_service.families.operations.recorded_state import (
    AVAILABILITY_STATE_NOT_APPLICABLE_RESOURCE_TYPES,
    AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE,
    OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES,
    OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE,
    PROVIDER_AVAILABILITY_STATE_NOT_EXPOSED_RESOURCE_TYPES,
    PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES,
    SERVING_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE,
    RecordedStateObservation,
    recorded_resource_states,
)

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
        "source_identity": None,
        "authority": None,
    }
    assert states["provisioning"]["value"] == "Succeeded"
    assert states["availability"]["value"] is None
    assert states["availability"]["reason"] == "provider_availability_state_not_exposed"
    assert projected["status"] == "Running"
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


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("operationalState", "Running"),
        ("dnsResolverState", "Connected"),
        ("resourceState", "Active"),
        ("userVisibleState", "Ready"),
    ],
)
def test_reviewed_operational_paths_are_retained(path: str, value: str) -> None:
    fact = _state({"properties": {path: value}})
    assert fact["value"] == value
    assert fact["source_path"] == f"properties.{path}"


def test_snapshot_columns_qualify_legacy_values_without_replacing_effective_time() -> None:
    states = recorded_resource_states(
        {"properties": {"runningStatus": "Running", "provisioningState": "Succeeded"}},
        resource_type="compute.container-app",
        observation=RecordedStateObservation(
            generation="generation-1",
            observed_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
            recorded_at=datetime(2026, 9, 5, 0, 1, tzinfo=UTC),
        ),
        now=datetime(2026, 9, 5, 0, 5, tzinfo=UTC),
    )
    assert states["operational"]["observed_at"] == "2026-09-05T00:00:00+00:00"
    assert states["operational"]["recorded_at"] == "2026-09-05T00:01:00+00:00"
    assert states["operational"]["freshness"] == "fresh"
    assert states["provisioning"]["freshness"] == "fresh"


def test_unclassified_resource_missing_state_has_a_distinct_reason() -> None:
    states = recorded_resource_states({}, resource_type="unclassified-resource", now=NOW)
    assert states["operational"]["reason"] == "resource_type_unclassified"


def test_missing_state_separates_source_provider_and_applicability_outcomes() -> None:
    mapped = recorded_resource_states({}, resource_type="compute.container-app", now=NOW)
    application_insights = recorded_resource_states(
        {},
        resource_type="application-insights",
        now=NOW,
    )
    log_workspace = recorded_resource_states({}, resource_type="log-workspace", now=NOW)
    not_applicable = recorded_resource_states({}, resource_type="resource-group", now=NOW)
    unresolved = recorded_resource_states({}, resource_type="downstream.custom", now=NOW)
    assert mapped["operational"]["reason"] == "state_source_not_recorded"
    assert application_insights["operational"]["reason"] == "state_not_applicable"
    assert application_insights["availability"]["reason"] == "state_not_applicable"
    assert log_workspace["operational"]["reason"] == "state_not_applicable"
    assert log_workspace["availability"]["reason"] == "state_source_not_recorded"
    assert not_applicable["operational"]["reason"] == "state_not_applicable"
    assert not_applicable["availability"]["reason"] == ("provider_availability_state_not_exposed")
    assert unresolved["operational"]["reason"] == "state_applicability_unknown"


@pytest.mark.parametrize(
    "reason",
    ["resource_health_not_modeled", "resource_health_target_limit"],
)
def test_missing_availability_preserves_the_reviewed_resource_health_reason(
    reason: str,
) -> None:
    states = recorded_resource_states(
        {
            "state_fact_unavailable_reasons": {
                "availabilityState": reason,
            }
        },
        resource_type="compute.vm",
        now=NOW,
    )

    assert states["availability"]["value"] is None
    assert states["availability"]["reason"] == reason


def test_activity_operation_status_does_not_replace_search_operational_state() -> None:
    states = recorded_resource_states(
        {
            "status": "running",
            "operationStatus": "Succeeded",
        },
        resource_type="search-service",
        now=NOW,
    )

    assert states["operational"]["value"] == "running"
    assert states["operational"]["source_path"] == "status"


def test_unreviewed_state_unavailability_reason_does_not_cross_the_read_boundary() -> None:
    states = recorded_resource_states(
        {
            "state_fact_unavailable_reasons": {
                "availabilityState": "provider supplied detail",
            }
        },
        resource_type="compute.vm",
        now=NOW,
    )

    assert states["availability"]["reason"] == "state_source_not_recorded"


def test_resource_type_applicability_rejects_unreviewed_supplied_state() -> None:
    resource_group = recorded_resource_states(
        {"status": "Succeeded"},
        resource_type="resource-group",
        now=NOW,
    )
    application_insights = recorded_resource_states(
        {"availabilityState": "Available"},
        resource_type="application-insights",
        now=NOW,
    )
    function = recorded_resource_states(
        {"status": "Running", "state": "Running"},
        resource_type="compute.function",
        now=NOW,
    )

    assert resource_group["operational"]["value"] is None
    assert resource_group["operational"]["reason"] == "state_not_applicable"
    assert application_insights["availability"]["value"] is None
    assert application_insights["availability"]["reason"] == "state_not_applicable"
    assert function["operational"]["source_path"] == "state"
    for resource_type in ("application-insights", "log-workspace", "resource-group"):
        projected = _resource_projection(
            InventoryInstanceResource(
                resource_id=f"{resource_type}-1",
                resource_type=resource_type,
                properties={"status": "Running", "provisioningState": "Succeeded"},
                last_seen=None,
            ),
            root_id=None,
            now=NOW,
        )
        assert projected["status"] is None


@pytest.mark.parametrize(
    ("resource_type", "properties", "expected_path", "expected_value"),
    [
        (
            "compute.function",
            {"status": "Running", "state": "Stopped"},
            "state",
            "Stopped",
        ),
        (
            "compute.vm",
            {
                "status": "Running",
                "state": "Started",
                "properties": {"powerState": {"code": "PowerState/deallocated"}},
            },
            "properties.powerState.code",
            "PowerState/deallocated",
        ),
        (
            "static-web-app",
            {
                "status": "Running",
                "provisioningState": "Succeeded",
                "staticSiteEnvironmentStatus": "Ready",
            },
            "staticSiteEnvironmentStatus",
            "Ready",
        ),
    ],
)
def test_operational_state_and_legacy_status_share_resource_type_paths(
    resource_type: str,
    properties: dict[str, object],
    expected_path: str,
    expected_value: str,
) -> None:
    projected = _resource_projection(
        InventoryInstanceResource(
            resource_id=f"{resource_type}-1",
            resource_type=resource_type,
            properties=properties,
            last_seen=None,
        ),
        root_id=None,
        now=NOW,
    )

    states = projected["states"]
    assert isinstance(states, dict)
    operational = states["operational"]
    assert isinstance(operational, dict)
    assert operational["source_path"] == expected_path
    assert operational["value"] == expected_value
    assert projected["status"] == expected_value


def test_kubernetes_unknown_readiness_remains_a_recorded_state() -> None:
    states = recorded_resource_states(
        {"ready_status": "Unknown"},
        resource_type="kubernetes.node",
        now=NOW,
    )

    assert states["operational"]["value"] == "Unknown"
    assert states["operational"]["source_path"] == "ready_status"


def test_private_endpoint_approval_does_not_become_operational_health() -> None:
    properties = {
        "properties": {
            "provisioningState": "Succeeded",
            "privateLinkServiceConnections": [
                {
                    "properties": {
                        "privateLinkServiceConnectionState": {
                            "status": "Approved",
                        }
                    }
                }
            ],
        }
    }
    states = recorded_resource_states(
        properties,
        resource_type="network.private-endpoint",
        now=NOW,
    )
    projected = _resource_projection(
        InventoryInstanceResource(
            resource_id="private-endpoint-1",
            resource_type="network.private-endpoint",
            properties=properties,
            last_seen=None,
        ),
        root_id=None,
        now=NOW,
    )

    assert states["operational"]["value"] is None
    assert states["operational"]["reason"] == "provider_operational_state_not_exposed"
    assert states["provisioning"]["value"] == "Succeeded"
    assert projected["status"] is None


def test_every_canonical_resource_type_has_a_reviewed_operational_state_outcome() -> None:
    vocabulary = (
        Path(__file__).resolve().parents[3] / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    ).read_text(encoding="utf-8")
    canonical = set(
        re.findall(
            r"^  - id: ([a-z][a-z0-9.-]+)$",
            vocabulary.split("types:\n", maxsplit=1)[1],
            flags=re.MULTILINE,
        )
    )
    classified = (
        set(OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE)
        | OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES
        | PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES
        | {"unclassified-resource"}
    )
    assert classified == canonical
    assert OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES.isdisjoint(
        PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES
    )
    assert set(AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE).isdisjoint(
        AVAILABILITY_STATE_NOT_APPLICABLE_RESOURCE_TYPES
    )
    availability_classified = (
        set(AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE)
        | AVAILABILITY_STATE_NOT_APPLICABLE_RESOURCE_TYPES
        | PROVIDER_AVAILABILITY_STATE_NOT_EXPOSED_RESOURCE_TYPES
        | {"unclassified-resource"}
    )
    assert availability_classified == canonical
    assert set(AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE).isdisjoint(
        PROVIDER_AVAILABILITY_STATE_NOT_EXPOSED_RESOURCE_TYPES
    )
    assert AVAILABILITY_STATE_NOT_APPLICABLE_RESOURCE_TYPES.isdisjoint(
        PROVIDER_AVAILABILITY_STATE_NOT_EXPOSED_RESOURCE_TYPES
    )


@pytest.mark.parametrize("resource_type", ["compute.image", "network.firewall-policy"])
def test_configuration_resources_have_reviewed_missing_state_outcomes(
    resource_type: str,
) -> None:
    states = recorded_resource_states({}, resource_type=resource_type, now=NOW)

    assert states["operational"]["reason"] == "state_not_applicable"
    assert states["availability"]["reason"] == "provider_availability_state_not_exposed"


@pytest.mark.parametrize(
    ("resource_type", "path", "value"),
    [
        ("disk", "diskState", "Reserved"),
        ("disk-snapshot", "snapshotAccessState", "Available"),
        ("network.registered-domain", "registrationStatus", "Active"),
        ("network.private-dns-zone-link", "virtualNetworkLinkState", "Completed"),
        ("search-service", "status", "running"),
    ],
)
def test_resource_specific_state_paths_are_retained(
    resource_type: str,
    path: str,
    value: str,
) -> None:
    fact = recorded_resource_states(
        {"properties": {path: value}},
        resource_type=resource_type,
        observation=RecordedStateObservation(
            generation="generation-1",
            observed_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
            recorded_at=datetime(2026, 9, 5, 0, 1, tzinfo=UTC),
        ),
        now=NOW,
    )["operational"]
    assert fact["value"] == value
    assert fact["source_path"] == f"properties.{path}"
    assert fact["freshness"] == "fresh"
    assert fact["completeness"] == 1.0


def test_vm_run_command_execution_state_is_retained() -> None:
    fact = recorded_resource_states(
        {"properties": {"instanceView": {"executionState": "Succeeded"}}},
        resource_type="compute.vm-run-command",
        observation=RecordedStateObservation(
            generation="generation-1",
            observed_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
            recorded_at=datetime(2026, 9, 5, 0, 1, tzinfo=UTC),
        ),
        now=NOW,
    )["operational"]

    assert fact["value"] == "Succeeded"
    assert fact["source_path"] == "properties.instanceView.executionState"
    assert fact["freshness"] == "fresh"
    assert fact["completeness"] == 1.0


def test_model_serving_state_preserves_telemetry_provenance() -> None:
    metadata = _metadata(
        authority="telemetry",
        source_identity="azure-monitor-model-serving",
        source_revision="azure-monitor-model-serving:sha256:" + "1" * 64,
        evidence_refs=["azure-monitor-model-serving:sha256:" + "1" * 64],
    )
    states = recorded_resource_states(
        {
            "servingState": "Serving",
            "state_fact_metadata": {"servingState": metadata},
        },
        resource_type="llm-model-deployment",
        now=NOW,
    )

    assert states["serving"]["value"] == "Serving"
    assert states["serving"]["source_path"] == "servingState"
    assert states["serving"]["source_identity"] == "azure-monitor-model-serving"
    assert states["serving"]["authority"] == "telemetry"


def test_model_serving_unavailability_reason_is_preserved_without_a_value() -> None:
    states = recorded_resource_states(
        {
            "state_fact_unavailable_reasons": {
                "servingState": "model_serving_not_observed",
            }
        },
        resource_type="llm-model-deployment",
        now=NOW,
    )

    assert states["serving"]["value"] is None
    assert states["serving"]["reason"] == "model_serving_not_observed"
    assert "serving" not in recorded_resource_states(
        {},
        resource_type="compute.vm",
        now=NOW,
    )
    assert SERVING_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE == {
        "llm-model-deployment": ("servingState",)
    }


def test_model_serving_state_requires_explicit_telemetry_metadata() -> None:
    states = recorded_resource_states(
        {"servingState": "Serving"},
        resource_type="llm-model-deployment",
        observation=RecordedStateObservation(
            generation="generation-1",
            observed_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
            recorded_at=datetime(2026, 9, 5, 0, 1, tzinfo=UTC),
        ),
        now=NOW,
    )

    assert states["serving"]["value"] is None
    assert states["serving"]["source_path"] is None
    assert states["serving"]["reason"] == "state_metadata_not_recorded"


@pytest.mark.parametrize("resource_type", AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE)
def test_resource_health_availability_preserves_exact_evidence(resource_type: str) -> None:
    metadata = _metadata(
        source_identity="azure-resource-health",
        source_revision="azure-resource-health:sha256:" + "1" * 64,
        effective_at="2026-09-05T00:04:00+00:00",
        recorded_at="2026-09-05T00:04:30+00:00",
        evidence_cutoff="2026-09-05T00:04:30+00:00",
        freshness_ceiling_seconds=300,
        evidence_refs=["azure-resource-health:sha256:" + "1" * 64],
    )
    states = recorded_resource_states(
        {
            "availabilityState": "Available",
            "state_fact_metadata": {"availabilityState": metadata},
        },
        resource_type=resource_type,
        now=NOW,
    )

    assert states["availability"] == {
        "value": "Available",
        "source_path": "availabilityState",
        "observed_at": "2026-09-05T00:04:00+00:00",
        "recorded_at": "2026-09-05T00:04:30+00:00",
        "freshness": "fresh",
        "completeness": 1.0,
        "conflicts": [],
        "reason": None,
        "source_identity": "azure-resource-health",
        "authority": "provider",
    }
    unknown = recorded_resource_states(
        {
            "availabilityState": "Unknown",
            "state_fact_metadata": {"availabilityState": metadata},
        },
        resource_type=resource_type,
        now=NOW,
    )
    assert unknown["availability"]["value"] == "Unknown"


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
        "source_identity": None,
        "authority": None,
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


def test_recent_cutoff_confirms_an_old_effective_state_without_rewriting_time() -> None:
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
    assert fact["observed_at"] == "2026-09-04T00:00:00+00:00"
    assert fact["freshness"] == "fresh"
    assert fact["reason"] is None


def test_static_web_app_ready_uses_current_evidence_cutoff_for_freshness() -> None:
    states = recorded_resource_states(
        {
            "staticSiteEnvironmentStatus": "Ready",
            "state_fact_metadata": {
                "staticSiteEnvironmentStatus": _metadata(
                    source_identity="azure-static-web-app-default-environment",
                    effective_at="2026-08-01T00:00:00+00:00",
                )
            },
        },
        resource_type="static-web-app",
        now=NOW,
    )

    assert states["operational"]["value"] == "Ready"
    assert states["operational"]["observed_at"] == "2026-08-01T00:00:00+00:00"
    assert states["operational"]["freshness"] == "fresh"
    assert states["operational"]["reason"] is None


@pytest.mark.parametrize(
    "missing", ["effective_at", "recorded_at", "lane", "authority", "synthetic"]
)
def test_missing_observation_metadata_never_becomes_fresh(missing: str) -> None:
    metadata = _metadata()
    metadata.pop(missing)
    fact = _state({"state": "Running", "state_fact_metadata": {"state": metadata}})
    assert fact["value"] == "Running"
    assert fact["freshness"] == "unknown"
    if missing == "authority":
        assert fact["authority"] is None


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
