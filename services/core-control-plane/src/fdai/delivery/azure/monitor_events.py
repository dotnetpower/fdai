"""Normalize bounded Azure Monitor push payloads into authority-free Events."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid5

from fdai_service_contracts.azure_monitor import (
    AzureMonitorNormalizationError,
    normalize_common_alert_schema,
)

from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode

_EVENT_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_MAX_DIAGNOSTIC_RECORDS = 1_000
_MAX_TEXT = 512


@dataclass(frozen=True, slots=True)
class DiagnosticNormalizerOptions:
    """Select metric records that may enter the normalized event stream."""

    metric_whitelist: tuple[str, ...]
    max_records: int = _MAX_DIAGNOSTIC_RECORDS

    def __post_init__(self) -> None:
        if not self.metric_whitelist:
            raise ValueError("metric_whitelist MUST be non-empty")
        if self.metric_whitelist != tuple(sorted(self.metric_whitelist)):
            raise ValueError("metric_whitelist MUST be unique and ordered")
        if len(self.metric_whitelist) != len(set(self.metric_whitelist)):
            raise ValueError("metric_whitelist MUST be unique and ordered")
        if any(not item.strip() or len(item) > _MAX_TEXT for item in self.metric_whitelist):
            raise ValueError("metric_whitelist contains an invalid metric name")
        if not 1 <= self.max_records <= _MAX_DIAGNOSTIC_RECORDS:
            raise ValueError(f"max_records MUST be in [1, {_MAX_DIAGNOSTIC_RECORDS}]")


def normalize_diagnostic_records(
    payload: Mapping[str, Any],
    *,
    options: DiagnosticNormalizerOptions,
    ingested_at: datetime,
) -> tuple[Event, ...]:
    """Normalize whitelisted AllMetrics records and skip all other categories."""

    records = payload.get("records")
    if not isinstance(records, list):
        raise AzureMonitorNormalizationError("diagnostic payload records MUST be an array")
    if len(records) > options.max_records:
        raise AzureMonitorNormalizationError("diagnostic payload exceeds the record bound")
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise AzureMonitorNormalizationError("ingested_at MUST be timezone-aware")

    allowed = frozenset(options.metric_whitelist)
    events: list[Event] = []
    for raw in records:
        record = _mapping(raw, field="records[]")
        if record.get("category") != "AllMetrics":
            continue
        metric_name = _text(record, "metricName")
        if metric_name not in allowed:
            continue
        detected_at = _timestamp(record, "time").astimezone(UTC)
        if detected_at > ingested_at:
            raise AzureMonitorNormalizationError("diagnostic record time MUST NOT be in the future")
        provider_ref = _text(record, "resourceId")
        resource_ref = to_neutral_id(provider_ref)
        values = _metric_values(record)
        identity = (
            f"diagnostic-metric|{resource_ref}|{metric_name}|"
            f"{detected_at.isoformat()}|{_digest(repr(sorted(values.items())))}"
        )
        events.append(
            Event(
                schema_version="1.0.0",
                event_id=uuid5(_EVENT_NAMESPACE, identity),
                idempotency_key=f"azure-diagnostic:{_digest(identity)}",
                correlation_id=None,
                source="azure_diagnostic_metrics",
                event_type="metric_observed",
                resource_ref=resource_ref,
                payload={"metric_name": metric_name, **values},
                detected_at=detected_at,
                ingested_at=ingested_at,
                incident_correlation=IncidentCorrelation.NONE,
                mode=Mode.SHADOW,
            )
        )
    return tuple(events)


def _metric_values(record: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in ("average", "minimum", "maximum", "total", "count"):
        value = record.get(field)
        if value is None:
            continue
        if isinstance(value, bool):
            raise AzureMonitorNormalizationError(f"metric field {field!r} MUST be numeric")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise AzureMonitorNormalizationError(f"metric field {field!r} MUST be numeric") from exc
        if not number.is_finite():
            raise AzureMonitorNormalizationError(f"metric field {field!r} MUST be finite")
        values[field] = format(number.normalize(), "f")
    if not values:
        raise AzureMonitorNormalizationError("diagnostic metric has no numeric value")
    return values


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AzureMonitorNormalizationError(f"{field} MUST be an object")
    return value


def _text(values: Mapping[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > _MAX_TEXT:
        raise AzureMonitorNormalizationError(f"{field} MUST contain 1 to {_MAX_TEXT} characters")
    return value.strip()


def _timestamp(values: Mapping[str, Any], field: str) -> datetime:
    raw = _text(values, field)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AzureMonitorNormalizationError(f"{field} MUST be RFC 3339") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise AzureMonitorNormalizationError(f"{field} MUST include a timezone")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AzureMonitorNormalizationError",
    "DiagnosticNormalizerOptions",
    "normalize_common_alert_schema",
    "normalize_diagnostic_records",
]
