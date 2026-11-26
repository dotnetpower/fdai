"""External distributed-trace ingestion - CSP-neutral wire (Layer-0 #8).

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.2``.

Consumes spans from the customer's trace backend (App Insights, Tempo,
Jaeger, Honeycomb) so RCA can walk a request across services. Async by
contract - real trace queries are I/O-bound.

The upstream default binding is :class:`NoopTraceQueryProvider`. Real
adapters live under ``delivery/<vendor>/`` and are bound at the
composition root; ``core/`` never imports a vendor client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TraceQuery:
    """Filter over the trace store."""

    trace_id: str | None = None
    service: str | None = None
    operation: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    since: datetime | None = None
    until: datetime | None = None
    min_duration: timedelta | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class Span:
    """One distributed-trace span."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    start: datetime
    duration: timedelta
    status: str
    """W3C-style status: ``ok`` / ``error`` / ``unset``."""
    labels: Mapping[str, str] = field(default_factory=dict)


class TraceQueryProviderError(RuntimeError):
    """Raised on any unrecoverable provider failure - fail-closed."""


@runtime_checkable
class TraceQueryProvider(Protocol):
    """Async iterator over trace spans."""

    def query(self, query: TraceQuery) -> AsyncIterator[Span]:
        """Stream spans matching ``query`` in start-time order."""
        ...


class NoopTraceQueryProvider:
    """Upstream default - empty result for every query."""

    async def query(self, query: TraceQuery) -> AsyncIterator[Span]:  # noqa: ARG002 - Protocol conformance
        for _ in ():
            yield _  # pragma: no cover - unreachable


def _as_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC) if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class StaticTraceQueryProvider:
    """Deterministic in-memory provider for tests."""

    def __init__(self, spans: Sequence[Span]) -> None:
        self._spans: tuple[Span, ...] = tuple(sorted(spans, key=lambda s: _as_utc(s.start)))

    async def query(self, query: TraceQuery) -> AsyncIterator[Span]:
        if query.limit is not None and query.limit <= 0:
            return
        since_utc = _as_utc(query.since) if query.since is not None else None
        until_utc = _as_utc(query.until) if query.until is not None else None
        matched = 0
        for span in self._spans:
            if query.trace_id is not None and span.trace_id != query.trace_id:
                continue
            if query.service is not None and span.service != query.service:
                continue
            if query.operation is not None and span.operation != query.operation:
                continue
            span_start = _as_utc(span.start)
            if since_utc is not None and span_start < since_utc:
                continue
            if until_utc is not None and span_start > until_utc:
                continue
            if query.min_duration is not None and span.duration < query.min_duration:
                continue
            if any(span.labels.get(k) != v for k, v in query.labels.items()):
                continue
            yield span
            matched += 1
            if query.limit is not None and matched >= query.limit:
                return


__all__ = [
    "NoopTraceQueryProvider",
    "Span",
    "StaticTraceQueryProvider",
    "TraceQuery",
    "TraceQueryProvider",
    "TraceQueryProviderError",
]
