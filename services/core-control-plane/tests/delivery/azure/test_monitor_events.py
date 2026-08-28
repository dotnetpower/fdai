"""Azure Monitor push payload normalization tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.azure.monitor_events import (
    AzureMonitorNormalizationError,
    DiagnosticNormalizerOptions,
    normalize_common_alert_schema,
    normalize_diagnostic_records,
)
from fdai.shared.contracts.models.event import Event

_NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
_TARGET = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.ContainerService/"
    "managedClusters/aks-example"
)


def _alert(*, condition: str = "Fired") -> dict[str, object]:
    essentials: dict[str, object] = {
        "alertId": "alert-instance-1",
        "alertRule": "example-cpu-alert",
        "severity": "Sev2",
        "signalType": "Metric",
        "monitorCondition": condition,
        "monitoringService": "Platform",
        "alertTargetIDs": [_TARGET],
        "firedDateTime": (_NOW - timedelta(seconds=30)).isoformat(),
        "resolvedDateTime": (_NOW - timedelta(seconds=10)).isoformat(),
    }
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {"essentials": essentials, "alertContext": {}},
    }


def test_common_alert_fired_and_resolved_are_replay_stable() -> None:
    fired = normalize_common_alert_schema(_alert(), ingested_at=_NOW)
    replay = normalize_common_alert_schema(_alert(), ingested_at=_NOW)
    resolved = normalize_common_alert_schema(_alert(condition="Resolved"), ingested_at=_NOW)

    assert fired == replay
    assert len(fired) == 1
    assert fired[0].event_type == "metric_alert_fired"
    assert resolved[0].event_type == "metric_alert_resolved"
    assert fired[0].resource_ref is not None
    assert fired[0].resource_ref == to_neutral_id(_TARGET)
    assert "00000000-0000-0000-0000-000000000001" not in str(fired[0].payload)
    assert fired[0].mode == "shadow"
    assert fired[0].decision is None
    assert Event.model_validate(fired[0].model_dump(mode="json")).mode.value == "shadow"


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda body: body.update(schemaId="legacy"), "schema"),
        (
            lambda body: body["data"]["essentials"].update(monitorCondition="Unknown"),
            "monitorCondition",
        ),
        (
            lambda body: body["data"]["essentials"].update(alertTargetIDs=[]),
            "alertTargetIDs",
        ),
        (
            lambda body: body["data"]["essentials"].update(
                firedDateTime=(_NOW + timedelta(minutes=1)).isoformat()
            ),
            "future",
        ),
    ),
)
def test_common_alert_rejects_malformed_or_future_evidence(
    mutate: object,
    message: str,
) -> None:
    body = _alert()
    mutate(body)  # type: ignore[operator]
    with pytest.raises(AzureMonitorNormalizationError, match=message):
        normalize_common_alert_schema(body, ingested_at=_NOW)


def _diagnostic_record(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "time": (_NOW - timedelta(seconds=15)).isoformat(),
        "resourceId": _TARGET,
        "category": "AllMetrics",
        "metricName": "node_cpu_percent",
        "average": 82.5,
        "count": 4,
    }
    values.update(overrides)
    return values


def test_diagnostic_normalizer_emits_only_whitelisted_metrics() -> None:
    options = DiagnosticNormalizerOptions(metric_whitelist=("http_429_rate", "node_cpu_percent"))
    events = normalize_diagnostic_records(
        {
            "records": [
                _diagnostic_record(),
                _diagnostic_record(metricName="ignored_metric"),
                _diagnostic_record(category="AuditEvent"),
            ]
        },
        options=options,
        ingested_at=_NOW,
    )

    assert len(events) == 1
    assert events[0].event_type == "metric_observed"
    assert events[0].incident_correlation.value == "none"
    assert events[0].payload == {
        "metric_name": "node_cpu_percent",
        "average": "82.5",
        "count": "4",
    }


@pytest.mark.parametrize(
    ("record", "message"),
    (
        (_diagnostic_record(average="NaN"), "finite"),
        (_diagnostic_record(average=None, count=None), "no numeric"),
        (_diagnostic_record(time=(_NOW + timedelta(minutes=1)).isoformat()), "future"),
    ),
)
def test_matching_diagnostic_record_fails_closed(
    record: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(AzureMonitorNormalizationError, match=message):
        normalize_diagnostic_records(
            {"records": [record]},
            options=DiagnosticNormalizerOptions(metric_whitelist=("node_cpu_percent",)),
            ingested_at=_NOW,
        )


def test_diagnostic_options_require_unique_ordered_metrics_and_bounds() -> None:
    with pytest.raises(ValueError, match="ordered"):
        DiagnosticNormalizerOptions(metric_whitelist=("z", "a"))
    with pytest.raises(ValueError, match="max_records"):
        DiagnosticNormalizerOptions(metric_whitelist=("a",), max_records=0)


def test_diagnostic_identity_is_stable_across_timestamp_offsets() -> None:
    options = DiagnosticNormalizerOptions(metric_whitelist=("node_cpu_percent",))
    utc_record = _diagnostic_record()
    offset_record = _diagnostic_record(
        time=(_NOW - timedelta(seconds=15))
        .astimezone(timezone(timedelta(hours=5, minutes=30)))
        .isoformat()
    )

    utc_event = normalize_diagnostic_records(
        {"records": [utc_record]},
        options=options,
        ingested_at=_NOW,
    )[0]
    offset_event = normalize_diagnostic_records(
        {"records": [offset_record]},
        options=options,
        ingested_at=_NOW,
    )[0]

    assert offset_event.detected_at.tzinfo is UTC
    assert offset_event.event_id == utc_event.event_id
    assert offset_event.idempotency_key == utc_event.idempotency_key
