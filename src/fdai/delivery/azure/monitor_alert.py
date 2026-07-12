"""Azure Monitor Common Alert Schema v2 -> FDAI ``Event`` normalizer.

Design contract: **push-based near-real-time detection path.** Where
:mod:`~fdai.delivery.azure.metrics_api` and
:mod:`~fdai.delivery.azure.metric_logs` **pull** samples on a periodic
tick (bounded below by the metric backend ingestion floor, 1-5 min),
this module normalizes the alert payload Azure Monitor **pushes** when
a Metric Alert Rule fires. End-to-end detection latency drops to
~30-90 s (rule evaluation window + delivery lag), and no analyzer
tick has to run.

Composition
-----------

The full push-based chain is::

    Metric Alert Rule (per resource, threshold in Terraform)
      -> Action Group (webhook OR event-hub receiver)
      -> Diagnostic transport
            option A: HTTPS POST to FDAI webhook route
                      (:mod:`fdai.delivery.read_api.routes.azure_monitor_webhook`)
            option B: Azure Event Hub -> existing Kafka consumer
      -> normalize_common_alert_schema()  <-- this module
      -> Event on the ingest topic
      -> standard trust-router + risk-gate

The normalizer is a **pure function** with no I/O: a caller supplies the
already-parsed JSON dict and gets an :class:`Event` back (or a
``ValueError`` on a malformed payload). That keeps it unit-testable
without a live Azure alert firing, and it lets a fork wire any transport
(webhook, Event Hub, Service Bus, direct HTTP) in front of it.

Common Alert Schema v2 shape
----------------------------

Documented at
https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-common-schema
(schemaId ``"azureMonitorCommonAlertSchema"``). This module supports the
platform-metric signal type (``essentials.signalType == "Metric"``);
LogAlert / SmartDetector / ActivityLog / ServiceHealth signals are the
subject of sibling normalizers under this package (or a fork's own
adapter).

Resolved / recovery alerts
--------------------------

``monitorCondition == "Resolved"`` fires when the metric drops back
below the threshold. The normalizer emits a distinct
``event_type == "azure.metric_alert.resolved"`` so the trust-router can
close the correlated incident (matches the ``AnomalyFinding`` recovery
pattern in :mod:`fdai.core.detection.anomaly`). Callers that only care
about the fired state MAY filter these out upstream.

Safety
------

The payload is **untrusted** - it comes from a webhook / Kafka topic
we do not gate at the source. This module:

- validates every required field is a string / non-empty;
- caps ``payload`` size in the caller (webhook route ships a
  ``max_body_bytes`` guard);
- never interpolates payload text into an outbound URL, SQL, or shell;
- fail-closes with :class:`ValueError` on a shape mismatch rather
  than fabricating a "healthy" event to mask an intrusion attempt.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from fdai.shared.contracts.models import Event, Mode, Severity

_LOGGER = logging.getLogger(__name__)

_SCHEMA_ID_V2: Final[str] = "azureMonitorCommonAlertSchema"
_SOURCE: Final[str] = "azure_monitor.alert"
_EVENT_TYPE_FIRED: Final[str] = "azure.metric_alert.fired"
_EVENT_TYPE_RESOLVED: Final[str] = "azure.metric_alert.resolved"


# Azure Sev0..Sev4 map to FDAI Severity. Sev0/1 -> critical/high are
# obvious; Sev2/3/4 -> medium/low/low keeps every alert routed even
# when the fork's rule authors did not standardize on a subset.
_SEVERITY_MAP: Final[Mapping[str, Severity]] = {
    "sev0": Severity.CRITICAL,
    "sev1": Severity.HIGH,
    "sev2": Severity.MEDIUM,
    "sev3": Severity.LOW,
    "sev4": Severity.LOW,
}


@dataclass(frozen=True, slots=True)
class NormalizerOptions:
    """Optional caller-supplied knobs.

    ``default_mode`` gates whether the emitted event is ``SHADOW`` or
    ``ENFORCE`` - upstream defaults to shadow so a first-time deploy
    never auto-executes off a live alert (per the safety-invariants
    doc). ``correlation_id`` overrides the Azure ``alertId``-derived
    correlation so a webhook route that already threads its own
    correlation can preserve it.
    """

    default_mode: Mode = Mode.SHADOW
    correlation_id: str | None = None


def normalize_common_alert_schema(
    payload: Mapping[str, Any],
    *,
    options: NormalizerOptions | None = None,
    now: datetime | None = None,
) -> Event:
    """Return an :class:`Event` normalized from a Common Alert Schema v2 payload.

    Raises :class:`ValueError` when the payload does not conform - the
    caller (webhook route, Kafka consumer) treats the raise as a 4xx
    reject and drops the delivery without publishing.
    """
    opts = options or NormalizerOptions()
    ingested_at = now or datetime.now(tz=UTC)

    schema_id = payload.get("schemaId")
    if schema_id != _SCHEMA_ID_V2:
        raise ValueError(
            f"unsupported alert schemaId {schema_id!r} - only {_SCHEMA_ID_V2!r} "
            "is understood by normalize_common_alert_schema()"
        )
    data = _require_object(payload, "data")
    essentials = _require_object(data, "data.essentials")

    signal_type = essentials.get("signalType")
    if signal_type != "Metric":
        raise ValueError(
            f"unsupported essentials.signalType {signal_type!r} - "
            "normalize_common_alert_schema handles Metric alerts only "
            "(LogAlert / SmartDetector have their own normalizers)"
        )

    monitor_condition = essentials.get("monitorCondition")
    if monitor_condition not in ("Fired", "Resolved"):
        raise ValueError(
            f"unexpected monitorCondition {monitor_condition!r} - MUST be 'Fired' or 'Resolved'"
        )
    event_type = _EVENT_TYPE_FIRED if monitor_condition == "Fired" else _EVENT_TYPE_RESOLVED

    alert_id = _require_string(essentials, "essentials.alertId")
    alert_rule = _require_string(essentials, "essentials.alertRule")
    severity_raw = _require_string(essentials, "essentials.severity").lower()
    severity = _SEVERITY_MAP.get(severity_raw)
    if severity is None:
        raise ValueError(
            f"unknown essentials.severity {severity_raw!r} - MUST be one of {sorted(_SEVERITY_MAP)}"
        )

    fired_raw = _require_string(essentials, "essentials.firedDateTime")
    detected_at = _parse_iso8601(fired_raw)

    # alertTargetIDs is documented as a list; the first entry is the
    # primary resource. An empty list is a schema violation - alerts
    # always have at least one target - so fail-closed.
    targets = essentials.get("alertTargetIDs")
    if not isinstance(targets, list) or not targets:
        raise ValueError("essentials.alertTargetIDs MUST be a non-empty list of ARM ids")
    primary_target = targets[0]
    if not isinstance(primary_target, str) or not primary_target:
        raise ValueError("essentials.alertTargetIDs[0] MUST be a non-empty ARM id string")
    # ARM ids are case-insensitive; the pipeline consistently lowercases
    # them so a downstream label-filter comparison hits (matches the
    # convention in the Log Analytics and Metrics API adapters).
    resource_ref = primary_target.lower()

    # Deterministic idempotency: hash the alertId + monitorCondition +
    # firedDateTime so a retry of the same delivery folds to one event,
    # but a distinct fire (or a fired-then-resolved pair) is two events.
    idempotency_seed = f"{alert_id}|{monitor_condition}|{fired_raw}"
    idempotency_key = "azure_alert:" + hashlib.sha256(idempotency_seed.encode("utf-8")).hexdigest()

    # Correlation id: caller override wins, else fold the alertId itself
    # so every fire / resolved pair on the same rule shares one.
    correlation_id = opts.correlation_id or f"azure_alert:{alert_id}"

    # Alert context - safe subset the trust-router can consult without
    # the raw payload (which still lives under 'raw' for the audit trail).
    context: dict[str, Any] = {
        "alert_id": alert_id,
        "alert_rule": alert_rule,
        "severity": severity.value,
        "azure_severity": severity_raw,
        "monitor_condition": monitor_condition,
        "signal_type": signal_type,
        "monitoring_service": essentials.get("monitoringService"),
        "resource_ref": resource_ref,
        "resource_targets": [t.lower() for t in targets if isinstance(t, str) and t],
        "fired_at": fired_raw,
    }
    _fold_metric_conditions(context, data.get("alertContext"))
    description = essentials.get("description")
    if isinstance(description, str) and description:
        context["description"] = description

    payload_body: dict[str, Any] = {
        "azure_monitor_alert": context,
        # Preserve the raw payload so an audit / debug can reconstruct
        # the delivery deterministically without holding onto a webhook
        # log. Trust router treats it as opaque data (per the untrusted-
        # payload rule).
        "raw": dict(payload),
    }

    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source=_SOURCE,
        event_type=event_type,
        resource_ref=resource_ref,
        payload=payload_body,
        detected_at=detected_at,
        ingested_at=ingested_at,
        mode=opts.default_mode,
    )


def _require_object(container: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    """Return ``container[last]`` if it is a Mapping; else raise."""
    key = path.rsplit(".", 1)[-1]
    value = container.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} MUST be a JSON object; got {type(value).__name__}")
    return value


def _require_string(container: Mapping[str, Any], path: str) -> str:
    key = path.rsplit(".", 1)[-1]
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} MUST be a non-empty string")
    return value


def _parse_iso8601(raw: str) -> datetime:
    """Parse an ARM ISO-8601 timestamp; raise ``ValueError`` on failure."""
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"unparseable firedDateTime {raw!r}: {exc}") from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _fold_metric_conditions(context: dict[str, Any], alert_context: Any) -> None:
    """Extract the ``condition.allOf`` array into a compact list.

    Common Alert Schema v2 nests the actual metric / operator / threshold
    / measured value under ``alertContext.condition.allOf[]``. Surface
    the essentials as a flat, English-only list so the trust-router does
    not have to walk the raw envelope again. Silently skips a payload
    without a condition block - the ``essentials`` view above is still
    complete for routing.
    """
    if not isinstance(alert_context, Mapping):
        return
    condition = alert_context.get("condition")
    if not isinstance(condition, Mapping):
        return
    all_of = condition.get("allOf")
    if not isinstance(all_of, list):
        return
    conditions: list[dict[str, Any]] = []
    for entry in all_of:
        if not isinstance(entry, Mapping):
            continue
        summary: dict[str, Any] = {}
        for key in (
            "metricName",
            "operator",
            "threshold",
            "timeAggregation",
            "metricValue",
        ):
            if key in entry:
                summary[key] = entry[key]
        if summary:
            conditions.append(summary)
    if conditions:
        context["conditions"] = conditions
    window = condition.get("windowSize")
    if isinstance(window, str) and window:
        context["window_size"] = window


__all__ = [
    "NormalizerOptions",
    "normalize_common_alert_schema",
]
