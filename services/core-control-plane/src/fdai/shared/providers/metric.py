"""External metric ingestion - CSP-neutral wire contract (Layer-0 seam #6).

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.2``.

FDAI emits OpenTelemetry traces / metrics of its own via
``shared/telemetry``, but the workloads it operates on emit metrics into
whatever telemetry backend the customer runs (Prometheus, Azure Monitor
Logs, CloudWatch, Datadog). This Protocol is the seam that lets the
control plane **consume** those external metrics for anomaly detection,
SLO burn-rate evaluation, and RCA grounding.

Async by contract - a real backend query is I/O-bound and would block
the event loop otherwise, matching the same discipline as
:class:`~fdai.shared.providers.event_bus.EventBus`,
:class:`~fdai.shared.providers.state_store.StateStore`, and the other
async wire contracts under this package.

The upstream default binding is :class:`NoopMetricProvider` (returns an
empty result). Real adapters (Prometheus PromQL, Azure Monitor Logs
KQL, CloudWatch) land under ``delivery/<vendor>/`` and are wired at the
composition root; ``core/`` never imports a concrete backend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MetricQuery:
    """One point-in-time or ranged query for external metrics.

    ``metric_name`` is CSP-neutral (e.g. ``http.server.request.duration``);
    the concrete adapter maps it to its vendor's namespace. ``labels``
    filter series (e.g. ``{"resource_id": "vm-01"}``); ``since`` /
    ``until`` bound the time range (UTC).
    """

    metric_name: str
    labels: Mapping[str, str] = field(default_factory=dict)
    since: datetime | None = None
    until: datetime | None = None
    aggregation: str | None = None
    """Optional vendor-neutral aggregation hint: ``sum`` / ``avg`` /
    ``min`` / ``max`` / ``p50`` / ``p90`` / ``p99``. The adapter MAY
    ignore hints it cannot honor and return the raw series instead - the
    caller MUST NOT assume the hint took effect."""


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """One (timestamp, value, labels) sample from an external backend."""

    metric_name: str
    at: datetime
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)


class MetricProviderError(RuntimeError):
    """Raised on any unrecoverable provider failure.

    Fail-closed: the caller MUST NOT proceed to auto-remediate on a
    partial result; abstain and route to HIL per the safety-invariant
    rule in ``architecture.instructions.md``.
    """


@runtime_checkable
class MetricProvider(Protocol):
    """Async iterator over external metric samples."""

    def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        """Stream samples matching ``query`` in chronological order.

        Implementations SHOULD paginate transparently; the caller
        materializes with ``async for`` or ``[p async for p in ...]``.
        Empty result (no samples in the window) is a valid answer, NOT
        an error.
        """
        ...


class NoopMetricProvider:
    """Upstream default - returns an empty result for every query.

    Ships in P1 so downstream consumers (anomaly detector, SLO burn-rate
    evaluator) can be authored against a stable interface; a real
    adapter lands in a follow-up per
    :doc:`scope-expansion § 3.2 <../../../docs/roadmap/fork-and-sequencing/scope-expansion.md>`.
    """

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:  # noqa: ARG002 - Protocol conformance
        # Async generator that yields nothing. Cannot use `return` in
        # an async generator body; the empty `for` short-circuits.
        for _ in ():
            yield _  # pragma: no cover - unreachable


def _labels_match(sample_labels: Mapping[str, str], query_labels: Mapping[str, str]) -> bool:
    """Return True if every query label is present with the same value on the sample."""
    return all(sample_labels.get(k) == v for k, v in query_labels.items())


class StaticMetricProvider:
    """Deterministic in-memory provider for tests and dev.

    Backed by a static list of ``MetricPoint`` samples; the ``query``
    coroutine filters by name + labels + time window in memory. Never
    calls out to a network.
    """

    def __init__(self, samples: Sequence[MetricPoint]) -> None:
        self._samples: tuple[MetricPoint, ...] = tuple(samples)

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        for sample in self._samples:
            if sample.metric_name != query.metric_name:
                continue
            if query.since is not None and sample.at < query.since:
                continue
            if query.until is not None and sample.at > query.until:
                continue
            if not _labels_match(sample.labels, query.labels):
                continue
            yield sample


__all__ = [
    "MetricPoint",
    "MetricProvider",
    "MetricProviderError",
    "MetricQuery",
    "NoopMetricProvider",
    "StaticMetricProvider",
]
