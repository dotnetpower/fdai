"""Azure Monitor Common Alert Schema contract tests."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai_service_contracts.azure_monitor import (
    AzureMonitorEvent,
    AzureMonitorNormalizationError,
    normalize_common_alert_schema,
)
from pydantic import ValidationError

_NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
_TARGET = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Example/widgets/a"
)


def _payload(*, condition: str = "Fired") -> dict[str, object]:
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
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
        },
    }


def test_common_alert_is_replay_stable_and_sanitized() -> None:
    first = normalize_common_alert_schema(_payload(), ingested_at=_NOW)
    second = normalize_common_alert_schema(_payload(), ingested_at=_NOW)

    assert first == second
    assert first[0].event_type == "metric_alert_fired"
    assert first[0].mode == "shadow"
    assert first[0].decision is None
    assert _TARGET not in str(first[0].payload)
    assert AzureMonitorEvent.model_validate_json(first[0].model_dump_json()) == first[0]


def test_common_alert_resolved_uses_resolved_timestamp() -> None:
    event = normalize_common_alert_schema(
        _payload(condition="Resolved"),
        ingested_at=_NOW,
    )[0]

    assert event.event_type == "metric_alert_resolved"
    assert event.detected_at == _NOW - timedelta(seconds=10)


def test_common_alert_rejects_future_or_unsupported_evidence() -> None:
    payload = _payload()
    essentials = payload["data"]["essentials"]  # type: ignore[index]
    essentials["firedDateTime"] = (_NOW + timedelta(seconds=1)).isoformat()  # type: ignore[index]
    with pytest.raises(AzureMonitorNormalizationError, match="future"):
        normalize_common_alert_schema(payload, ingested_at=_NOW)

    with pytest.raises(AzureMonitorNormalizationError, match="schema"):
        normalize_common_alert_schema({"schemaId": "legacy"}, ingested_at=_NOW)


def test_common_alert_event_cannot_raise_authority() -> None:
    event = normalize_common_alert_schema(_payload(), ingested_at=_NOW)[0]

    with pytest.raises(ValidationError):
        AzureMonitorEvent.model_validate({**event.model_dump(), "mode": "enforce"})


def test_equivalent_timestamp_offsets_share_one_event_identity() -> None:
    utc_payload = _payload()
    offset_payload = _payload()
    offset = timezone(timedelta(hours=2))
    essentials = offset_payload["data"]["essentials"]  # type: ignore[index]
    essentials["firedDateTime"] = (  # type: ignore[index]
        (_NOW - timedelta(seconds=30)).astimezone(offset).isoformat()
    )

    utc_event = normalize_common_alert_schema(utc_payload, ingested_at=_NOW)[0]
    offset_event = normalize_common_alert_schema(offset_payload, ingested_at=_NOW)[0]

    assert offset_event.detected_at.tzinfo is UTC
    assert offset_event.event_id == utc_event.event_id
    assert offset_event.idempotency_key == utc_event.idempotency_key
