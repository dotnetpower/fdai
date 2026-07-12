"""Tests for the Azure Monitor Common Alert Schema v2 normalizer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.delivery.azure.monitor_alert import (
    NormalizerOptions,
    normalize_common_alert_schema,
)
from fdai.shared.contracts.models import Mode, Severity

# ---------------------------------------------------------------------------
# A minimal, fully-populated Common Alert Schema v2 fixture.
# Every field required by the normalizer is present; extra fields
# defend against a schema addition breaking the tests.
# ---------------------------------------------------------------------------


def _fired_payload(
    *,
    monitor_condition: str = "Fired",
    severity: str = "Sev2",
    signal_type: str = "Metric",
    targets: list[str] | None = None,
    fired: str = "2026-07-13T00:15:00Z",
    with_context: bool = True,
) -> dict:
    if targets is None:
        targets = [
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/example-rg/providers/Microsoft.DBforMySQL"
            "/flexibleServers/example-mysql"
        ]
    payload: dict = {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
                "alertId": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000"
                    "/providers/Microsoft.AlertsManagement/alerts/abc-123"
                ),
                "alertRule": "MySQL-cpu-over-90",
                "severity": severity,
                "signalType": signal_type,
                "monitorCondition": monitor_condition,
                "monitoringService": "Platform",
                "alertTargetIDs": targets,
                "firedDateTime": fired,
                "description": "CPU sustained above 90% for 5 minutes.",
            }
        },
    }
    if with_context:
        payload["data"]["alertContext"] = {
            "condition": {
                "windowSize": "PT5M",
                "allOf": [
                    {
                        "metricName": "cpu_percent",
                        "operator": "GreaterThan",
                        "threshold": "90",
                        "timeAggregation": "Average",
                        "metricValue": 94.2,
                    }
                ],
            }
        }
    return payload


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_fired_metric_alert_maps_to_fired_event() -> None:
    event = normalize_common_alert_schema(_fired_payload())
    assert event.event_type == "azure.metric_alert.fired"
    assert event.source == "azure_monitor.alert"
    assert event.mode is Mode.SHADOW  # safety-invariant default
    assert event.resource_ref == (
        "/subscriptions/00000000-0000-0000-0000-000000000000"
        "/resourcegroups/example-rg/providers/microsoft.dbformysql"
        "/flexibleservers/example-mysql"
    )
    ctx = event.payload["azure_monitor_alert"]
    assert ctx["severity"] == Severity.MEDIUM.value  # Sev2 -> medium
    assert ctx["azure_severity"] == "sev2"
    assert ctx["alert_rule"] == "MySQL-cpu-over-90"
    assert ctx["conditions"] == [
        {
            "metricName": "cpu_percent",
            "operator": "GreaterThan",
            "threshold": "90",
            "timeAggregation": "Average",
            "metricValue": 94.2,
        }
    ]
    assert ctx["window_size"] == "PT5M"
    # Detected timestamp matches the alert's own firedDateTime.
    assert event.detected_at == datetime(2026, 7, 13, 0, 15, tzinfo=UTC)


def test_resolved_alert_emits_resolved_event_type() -> None:
    event = normalize_common_alert_schema(_fired_payload(monitor_condition="Resolved"))
    assert event.event_type == "azure.metric_alert.resolved"


def test_default_correlation_id_folds_by_alert_id() -> None:
    """Every fire/resolve pair on the same rule shares one correlation id."""
    fired = normalize_common_alert_schema(_fired_payload())
    resolved = normalize_common_alert_schema(
        _fired_payload(monitor_condition="Resolved", fired="2026-07-13T00:20:00Z")
    )
    assert fired.correlation_id == resolved.correlation_id


def test_options_correlation_id_wins() -> None:
    event = normalize_common_alert_schema(
        _fired_payload(), options=NormalizerOptions(correlation_id="req-42")
    )
    assert event.correlation_id == "req-42"


def test_options_enforce_mode_flows_to_event() -> None:
    event = normalize_common_alert_schema(
        _fired_payload(), options=NormalizerOptions(default_mode=Mode.ENFORCE)
    )
    assert event.mode is Mode.ENFORCE


def test_idempotency_key_is_deterministic_per_fired_payload() -> None:
    a = normalize_common_alert_schema(_fired_payload())
    b = normalize_common_alert_schema(_fired_payload())
    assert a.idempotency_key == b.idempotency_key


def test_idempotency_key_differs_across_fire_and_resolve() -> None:
    a = normalize_common_alert_schema(_fired_payload())
    b = normalize_common_alert_schema(
        _fired_payload(monitor_condition="Resolved", fired="2026-07-13T00:20:00Z")
    )
    assert a.idempotency_key != b.idempotency_key


def test_severity_mapping_covers_sev0_through_sev4() -> None:
    got = {
        "Sev0": normalize_common_alert_schema(_fired_payload(severity="Sev0")).payload[
            "azure_monitor_alert"
        ]["severity"],
        "Sev1": normalize_common_alert_schema(_fired_payload(severity="Sev1")).payload[
            "azure_monitor_alert"
        ]["severity"],
        "Sev2": normalize_common_alert_schema(_fired_payload(severity="Sev2")).payload[
            "azure_monitor_alert"
        ]["severity"],
        "Sev3": normalize_common_alert_schema(_fired_payload(severity="Sev3")).payload[
            "azure_monitor_alert"
        ]["severity"],
        "Sev4": normalize_common_alert_schema(_fired_payload(severity="Sev4")).payload[
            "azure_monitor_alert"
        ]["severity"],
    }
    assert got == {
        "Sev0": Severity.CRITICAL.value,
        "Sev1": Severity.HIGH.value,
        "Sev2": Severity.MEDIUM.value,
        "Sev3": Severity.LOW.value,
        "Sev4": Severity.LOW.value,
    }


def test_raw_payload_is_preserved_for_audit() -> None:
    payload = _fired_payload()
    event = normalize_common_alert_schema(payload)
    # Round-trip-safe: the raw envelope MUST land under 'raw' verbatim
    # so an audit reader can reconstruct the delivery.
    assert event.payload["raw"] == payload


def test_multiple_targets_are_lowercased_and_preserved() -> None:
    payload = _fired_payload(
        targets=[
            "/SUBSCRIPTIONS/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/RG/providers/Microsoft.DBforMySQL/flexibleServers/A",
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg/providers/Microsoft.DBforMySQL/flexibleServers/B",
        ]
    )
    event = normalize_common_alert_schema(payload)
    ctx = event.payload["azure_monitor_alert"]
    # First target is the primary resource_ref.
    assert event.resource_ref == ctx["resource_targets"][0]
    assert len(ctx["resource_targets"]) == 2
    # Every entry is lowercased.
    for t in ctx["resource_targets"]:
        assert t == t.lower()


def test_missing_alert_context_still_produces_valid_event() -> None:
    """A minimal payload without alertContext is still routable."""
    event = normalize_common_alert_schema(_fired_payload(with_context=False))
    assert event.event_type == "azure.metric_alert.fired"
    assert "conditions" not in event.payload["azure_monitor_alert"]


# ---------------------------------------------------------------------------
# Fail-closed shape validation
# ---------------------------------------------------------------------------


def test_rejects_wrong_schema_id() -> None:
    payload = _fired_payload()
    payload["schemaId"] = "azureMonitorCommonAlertSchemaV1"
    with pytest.raises(ValueError, match="unsupported alert schemaId"):
        normalize_common_alert_schema(payload)


def test_rejects_non_metric_signal_type() -> None:
    with pytest.raises(ValueError, match="signalType"):
        normalize_common_alert_schema(_fired_payload(signal_type="Log"))


def test_rejects_unknown_monitor_condition() -> None:
    with pytest.raises(ValueError, match="monitorCondition"):
        normalize_common_alert_schema(_fired_payload(monitor_condition="Unknown"))


def test_rejects_missing_alert_id() -> None:
    payload = _fired_payload()
    del payload["data"]["essentials"]["alertId"]
    with pytest.raises(ValueError, match="essentials.alertId"):
        normalize_common_alert_schema(payload)


def test_rejects_unknown_severity() -> None:
    with pytest.raises(ValueError, match="essentials.severity"):
        normalize_common_alert_schema(_fired_payload(severity="Sev99"))


def test_rejects_empty_alert_target_ids() -> None:
    with pytest.raises(ValueError, match="alertTargetIDs"):
        normalize_common_alert_schema(_fired_payload(targets=[]))


def test_rejects_non_string_alert_target() -> None:
    payload = _fired_payload()
    payload["data"]["essentials"]["alertTargetIDs"] = [None]
    with pytest.raises(ValueError, match="alertTargetIDs\\[0\\]"):
        normalize_common_alert_schema(payload)


def test_rejects_unparseable_fired_date_time() -> None:
    with pytest.raises(ValueError, match="firedDateTime"):
        normalize_common_alert_schema(_fired_payload(fired="not-a-date"))


def test_rejects_missing_data_object() -> None:
    with pytest.raises(ValueError, match="data MUST be a JSON object"):
        normalize_common_alert_schema({"schemaId": "azureMonitorCommonAlertSchema"})


# ---------------------------------------------------------------------------
# Round-trip via JSON to make sure the fixture parses like a real webhook.
# ---------------------------------------------------------------------------


def test_normalizer_survives_json_round_trip(tmp_path: Path) -> None:
    fixture = tmp_path / "alert.json"
    fixture.write_text(json.dumps(_fired_payload()), encoding="utf-8")
    loaded = json.loads(fixture.read_text(encoding="utf-8"))
    event = normalize_common_alert_schema(loaded)
    assert event.event_type == "azure.metric_alert.fired"
