"""Strict Azure Monitor Common Alert Schema normalization contract."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid5

from pydantic import Field

from fdai_service_contracts.executor_models import ContractBase

_EVENT_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_COMMON_ALERT_SCHEMA = "azureMonitorCommonAlertSchema"
_MAX_ALERT_TARGETS = 32
_MAX_TEXT = 512


class AzureMonitorNormalizationError(ValueError):
    """Reject malformed or oversized Azure Monitor alert evidence."""


class AzureMonitorEvent(ContractBase):
    """One authority-free Event mapping accepted by the Core ingress."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: UUID
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    source: Literal["azure_monitor_metric_alert"] = "azure_monitor_metric_alert"
    event_type: Literal["metric_alert_fired", "metric_alert_resolved"]
    resource_ref: Annotated[str, Field(min_length=1, max_length=4_096)]
    payload: dict[str, str]
    detected_at: datetime
    ingested_at: datetime
    incident_correlation: Literal["correlate"] = "correlate"
    tier: None = None
    decision: None = None
    mode: Literal["shadow"] = "shadow"


def normalize_common_alert_schema(
    payload: Mapping[str, Any],
    *,
    ingested_at: datetime,
) -> tuple[AzureMonitorEvent, ...]:
    """Normalize one Common Alert Schema body into one Event per exact target."""

    if payload.get("schemaId") != _COMMON_ALERT_SCHEMA:
        raise AzureMonitorNormalizationError("unsupported Azure Monitor alert schema")
    data = _mapping(payload.get("data"), field="data")
    essentials = _mapping(data.get("essentials"), field="data.essentials")
    alert_id = _text(essentials, "alertId")
    condition = _text(essentials, "monitorCondition")
    normalized_condition = condition.casefold()
    if normalized_condition not in {"fired", "resolved"}:
        raise AzureMonitorNormalizationError("monitorCondition MUST be Fired or Resolved")
    targets = _string_sequence(essentials.get("alertTargetIDs"), field="alertTargetIDs")
    if not 1 <= len(targets) <= _MAX_ALERT_TARGETS:
        raise AzureMonitorNormalizationError(
            f"alertTargetIDs MUST contain 1 to {_MAX_ALERT_TARGETS} values"
        )
    if len(targets) != len({target.casefold() for target in targets}):
        raise AzureMonitorNormalizationError("alertTargetIDs MUST be unique")
    detected_at = _timestamp(
        essentials,
        "firedDateTime" if normalized_condition == "fired" else "resolvedDateTime",
    )
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise AzureMonitorNormalizationError("ingested_at MUST be timezone-aware")
    if detected_at > ingested_at:
        raise AzureMonitorNormalizationError("alert detection time MUST NOT be in the future")

    alert_digest = _digest(alert_id)
    correlation_id = f"azure-alert:{alert_digest}"
    stable_payload = {
        "alert_rule_digest": _digest(_text(essentials, "alertRule")),
        "severity": _text(essentials, "severity"),
        "monitor_condition": normalized_condition,
        "signal_type": _text(essentials, "signalType"),
        "monitoring_service": _text(essentials, "monitoringService"),
    }
    events: list[AzureMonitorEvent] = []
    for target in sorted(targets, key=str.casefold):
        resource_ref = _to_neutral_id(target)
        identity = (
            f"common-alert|{alert_digest}|{resource_ref}|"
            f"{normalized_condition}|{detected_at.isoformat()}"
        )
        events.append(
            AzureMonitorEvent(
                event_id=uuid5(_EVENT_NAMESPACE, identity),
                idempotency_key=f"azure-monitor:{_digest(identity)}",
                correlation_id=correlation_id,
                event_type=(
                    "metric_alert_fired"
                    if normalized_condition == "fired"
                    else "metric_alert_resolved"
                ),
                resource_ref=resource_ref,
                payload=stable_payload,
                detected_at=detected_at,
                ingested_at=ingested_at,
            )
        )
    return tuple(events)


def _to_neutral_id(arm_id: str) -> str:
    trimmed = arm_id.strip()
    parts = [part for part in trimmed.strip("/").split("/") if part]
    if len(parts) < 2 or parts[0].casefold() != "subscriptions":
        raise AzureMonitorNormalizationError("alert target MUST be an Azure resource id")
    subscription_digest = hashlib.sha256(parts[1].casefold().encode("utf-8")).hexdigest()[:16]
    scope = f"scope-{subscription_digest}"
    marker = "/resourcegroups/"
    folded = trimmed.casefold()
    index = folded.find(marker)
    if index == -1:
        suffix = "/".join(part.casefold() for part in parts[2:])
        return f"{scope}/{suffix}" if suffix else scope
    return f"{scope}/resource-group{folded[index + len(marker) - 1 :]}"


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AzureMonitorNormalizationError(f"{field} MUST be an object")
    return value


def _text(values: Mapping[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > _MAX_TEXT:
        raise AzureMonitorNormalizationError(f"{field} MUST contain 1 to {_MAX_TEXT} characters")
    return value.strip()


def _string_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise AzureMonitorNormalizationError(f"{field} MUST be an array of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 2_048:
            raise AzureMonitorNormalizationError(f"{field} contains an invalid value")
        result.append(item.strip())
    return tuple(result)


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
    "AzureMonitorEvent",
    "AzureMonitorNormalizationError",
    "normalize_common_alert_schema",
]
