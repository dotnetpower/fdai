"""Azure Monitor Diagnostic Setting AllMetrics -> FDAI stream of ``Event``.

Design contract: the **fastest push path** in the near-real-time
detection stack. Where the alert-webhook path
(:mod:`~fdai.delivery.azure.monitor_alert`) fires when a rule condition
matches (~30-90 s), a Diagnostic Setting can route **raw metric
records** to an Event Hub as they land in the Azure Monitor pipeline
(~15-60 s). The consumer picks each record up and lets FDAI's own
:class:`~fdai.core.investigation.analyzer.ThresholdAnalyzer` +
:class:`~fdai.core.detection.anomaly.MetricAnomalyDetector` decide
whether the sample crosses a threshold - no per-resource alert rule
required.

Trade-off vs the alert-webhook path
-----------------------------------

- **Streaming (this module)**: fastest, cheapest per additional metric
  (one Diagnostic Setting per resource covers every metric it emits),
  but every record flows through FDAI. Higher ingest volume + FDAI
  owns the threshold. Best when the fork wants centralized rule
  authority and low-latency for many metrics per resource.
- **Alert-webhook**: bounded volume (only firings), but each rule +
  threshold lives in Azure and every new rule is a Terraform edit.
  Best when a small, well-known set of alerts drives autonomy.

A fork can pick either, or both - the two normalizers ship together so
the fork's composition root decides which the trust router sees.

Payload shape
-------------

Azure Monitor writes diagnostic records to Event Hub as a JSON array of
``records``. Each record carries::

    {
      "time": "2026-07-13T00:00:00.0000000Z",
      "resourceId": "/SUBSCRIPTIONS/.../..." | "/subscriptions/.../...",
      "metricName": "cpu_percent",
      "timeGrain": "PT1M",
      "count": 60,
      "total": 3540.0,
      "minimum": 42.0,
      "maximum": 88.0,
      "average": 59.0,
      "timeStamp": "2026-07-13T00:00:00.0000000Z"
    }

The AllMetrics category is documented at
https://learn.microsoft.com/azure/azure-monitor/essentials/resource-logs-schema

This module is a **pure function** :func:`normalize_diagnostic_records`
that takes the outer envelope and yields one :class:`Event` per record
matched by the caller's whitelist. Everything else - Event Hub client,
threshold decision, publish - lives outside. That keeps the normalizer
unit-testable without a live Event Hub, and it lets a fork wire the
consumer in whichever runtime it prefers (long-running Kafka consumer,
Container Apps Job cron, Azure Function).

Safety
------

- Payload is **untrusted** (Event Hub payload passed through Azure
  Monitor). Every field is validated by type before use;
  :class:`ValueError` on a shape mismatch so the caller drops the
  record without publishing.
- ``metric_whitelist`` caps which CSP-neutral metric names get lifted
  into events - a fork opts in per metric. Without a whitelist the
  function returns an empty tuple (fail-closed against a firehose).
- ``resource_id`` values are lowercased for the same reason as
  :mod:`~fdai.delivery.azure.metrics_api` (case-insensitive ARM ids;
  pipeline convention is lowercase).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from fdai.shared.contracts.models import Event, Mode

_LOGGER = logging.getLogger(__name__)

_SOURCE: Final[str] = "azure_monitor.diagnostic"
_EVENT_TYPE: Final[str] = "azure.metric_sample"


# Azure Monitor diagnostic records carry every aggregation column
# unconditionally (``average``, ``minimum``, ``maximum``, ``total``,
# ``count``). Map each to the same string vocabulary the analyzers
# already speak so a caller can filter to the one it wants.
_AGGREGATION_KEYS: Final[Mapping[str, str]] = {
    "average": "average",
    "minimum": "minimum",
    "maximum": "maximum",
    "total": "total",
    "count": "count",
}


@dataclass(frozen=True, slots=True)
class DiagnosticNormalizerOptions:
    """Caller-supplied knobs.

    ``metric_whitelist`` is the set of ``metricName`` values the caller
    accepts (Azure-native names, case-sensitive per the payload). An
    empty set means "reject all" - safer default than "accept all" for
    a streaming source we do not fully trust.

    ``aggregation`` selects which of the five aggregation columns
    populates the emitted :attr:`Event.payload['value']`. Default is
    ``average`` because that is what the threshold analyzers use most
    often.

    ``metric_name_map`` optionally renames an Azure-native metric name
    to the CSP-neutral one the analyzers already speak (e.g.
    ``"cpu_percent"`` -> ``"cpu_percent"``, ``"Percentage CPU"`` ->
    ``"cpu_percent"``). Absent from the map keeps the native name.

    ``default_mode`` gates the emitted event's autonomy mode; upstream
    default is ``SHADOW`` (safety invariant).

    ``correlation_id_prefix`` becomes ``{prefix}:{resource_id}:{metric}``
    so every sample of the same series folds to one correlated
    incident thread across ticks.
    """

    metric_whitelist: frozenset[str] = frozenset()
    aggregation: str = "average"
    metric_name_map: Mapping[str, str] | None = None
    default_mode: Mode = Mode.SHADOW
    correlation_id_prefix: str = "azure_metric_stream"

    def __post_init__(self) -> None:
        if self.aggregation not in _AGGREGATION_KEYS:
            raise ValueError(
                f"DiagnosticNormalizerOptions.aggregation MUST be one of "
                f"{sorted(_AGGREGATION_KEYS)}, got {self.aggregation!r}"
            )
        if not self.correlation_id_prefix:
            raise ValueError(
                "DiagnosticNormalizerOptions.correlation_id_prefix MUST be "
                "non-empty (used to fold samples of the same series)"
            )


def normalize_diagnostic_records(
    envelope: Any,
    *,
    options: DiagnosticNormalizerOptions,
    now: datetime | None = None,
) -> tuple[Event, ...]:
    """Turn a Diagnostic Setting Event Hub message into a tuple of events.

    ``envelope`` is the parsed JSON body (either a single record dict
    or the standard ``{"records": [...]}`` array wrapper). Records that
    do not pass the whitelist / shape checks are silently skipped -
    Event Hub delivery is at-least-once, so a partial batch is normal
    and the caller MUST NOT reject the whole envelope on one bad row.

    Raises :class:`ValueError` only for the outermost envelope shape;
    per-record failures produce a warning log and get skipped.
    """
    ingested_at = now or datetime.now(tz=UTC)
    records = _extract_records(envelope)
    if not records:
        return ()
    if not options.metric_whitelist:
        # Fail-closed: without an explicit whitelist we would emit
        # every metric of every resource, potentially thousands per
        # minute. The caller must opt in per metric.
        _LOGGER.warning(
            "diagnostic_stream_no_whitelist",
            extra={
                "reason": (
                    "DiagnosticNormalizerOptions.metric_whitelist is empty; "
                    "returning () rather than lift the full firehose"
                )
            },
        )
        return ()

    agg_key = _AGGREGATION_KEYS[options.aggregation]
    name_map = options.metric_name_map or {}

    events: list[Event] = []
    for i, record in enumerate(records):
        try:
            event = _normalize_one(
                record,
                agg_key=agg_key,
                agg_alias=options.aggregation,
                whitelist=options.metric_whitelist,
                name_map=name_map,
                default_mode=options.default_mode,
                correlation_prefix=options.correlation_id_prefix,
                ingested_at=ingested_at,
            )
        except ValueError as exc:
            _LOGGER.warning(
                "diagnostic_stream_skipped_record",
                extra={"index": i, "reason": str(exc)},
            )
            continue
        if event is not None:
            events.append(event)
    return tuple(events)


def _extract_records(envelope: Any) -> Sequence[Mapping[str, Any]]:
    """Return the record list from either shape Azure Monitor emits.

    The Event Hub SDK may deliver a single record inline (older
    Diagnostic Setting versions) or the wrapper object with a
    ``records`` list. Anything else raises :class:`ValueError` because
    it means the transport layer handed us something we do not
    understand.
    """
    if isinstance(envelope, list):
        # Some batches come as a bare list of records.
        return [r for r in envelope if isinstance(r, Mapping)]
    if not isinstance(envelope, Mapping):
        raise ValueError(
            f"diagnostic envelope MUST be a JSON object or array; got {type(envelope).__name__}"
        )
    if "records" in envelope:
        records = envelope["records"]
        if not isinstance(records, list):
            raise ValueError(
                f"diagnostic envelope 'records' MUST be a list; got {type(records).__name__}"
            )
        return [r for r in records if isinstance(r, Mapping)]
    # A single-record envelope: only accept if it carries the required
    # metricName + resourceId shape, so a random JSON object is not
    # silently treated as one metric sample.
    if "metricName" in envelope and "resourceId" in envelope:
        return [envelope]
    raise ValueError(
        "diagnostic envelope has no 'records' list and does not look like a "
        "single record (missing 'metricName' + 'resourceId')"
    )


def _normalize_one(
    record: Mapping[str, Any],
    *,
    agg_key: str,
    agg_alias: str,
    whitelist: frozenset[str],
    name_map: Mapping[str, str],
    default_mode: Mode,
    correlation_prefix: str,
    ingested_at: datetime,
) -> Event | None:
    """Normalize one metric record; return ``None`` when filtered out."""
    metric_native = record.get("metricName")
    if not isinstance(metric_native, str) or not metric_native:
        raise ValueError("record.metricName MUST be a non-empty string")
    if metric_native not in whitelist:
        return None  # silent skip - a whitelist miss is expected

    raw_resource = record.get("resourceId")
    if not isinstance(raw_resource, str) or not raw_resource:
        raise ValueError("record.resourceId MUST be a non-empty string")
    resource_ref = raw_resource.lower()

    ts_raw = record.get("timeStamp") or record.get("time")
    if not isinstance(ts_raw, str) or not ts_raw:
        raise ValueError("record.timeStamp / .time MUST be a non-empty string")
    detected_at = _parse_iso8601(ts_raw)

    if agg_key not in record:
        # Azure emits every aggregation column, but a malformed row may
        # be missing the one we asked for. Skip rather than fabricate a
        # zero-valued sample.
        return None
    raw_value = record[agg_key]
    if not isinstance(raw_value, int | float):
        raise ValueError(f"record.{agg_key} MUST be a number; got {type(raw_value).__name__}")
    value = float(raw_value)

    metric_name = name_map.get(metric_native, metric_native)

    idempotency_seed = f"{resource_ref}|{metric_name}|{ts_raw}"
    idempotency_key = (
        "azure_metric_stream:" + hashlib.sha256(idempotency_seed.encode("utf-8")).hexdigest()
    )

    correlation_id = f"{correlation_prefix}:{resource_ref}:{metric_name}"

    payload = {
        "azure_metric_sample": {
            "resource_ref": resource_ref,
            "metric_name": metric_name,
            "azure_metric_name": metric_native,
            "aggregation": agg_alias,
            "value": value,
            "time_grain": record.get("timeGrain"),
            "sample_time": ts_raw,
        },
        "raw": dict(record),
    }

    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source=_SOURCE,
        event_type=_EVENT_TYPE,
        resource_ref=resource_ref,
        payload=payload,
        detected_at=detected_at,
        ingested_at=ingested_at,
        mode=default_mode,
    )


def _parse_iso8601(raw: str) -> datetime:
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"unparseable diagnostic timestamp {raw!r}: {exc}") from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def iter_records_from_batch(batch: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    """Small utility: flatten a batch of envelopes into a record iterator.

    Handy for a Kafka consumer that receives a batch of Event Hub
    envelopes at once - the consumer feeds each to
    :func:`normalize_diagnostic_records` and this helper drains them
    lazily.
    """
    for envelope in batch:
        try:
            yield from _extract_records(envelope)
        except ValueError:  # noqa: PERF203 - per-envelope isolation
            continue


__all__ = [
    "DiagnosticNormalizerOptions",
    "iter_records_from_batch",
    "normalize_diagnostic_records",
]
