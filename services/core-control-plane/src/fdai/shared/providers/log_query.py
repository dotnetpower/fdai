"""External log ingestion - CSP-neutral wire contract (Layer-0 seam #7).

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.2``.

Consumes structured log records from the customer's log backend
(Log Analytics KQL, Loki LogQL, Elasticsearch, CloudWatch Logs) so RCA
can ground on real event text rather than only rule / policy citations.

Async by contract - a real query is I/O-bound. The upstream default
binding is :class:`NoopLogQueryProvider`; real adapters live under
``delivery/<vendor>/`` and are bound at the composition root.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LogQuery:
    """Filter over the log store.

    ``expression`` is the vendor-specific query string (KQL, LogQL,
    ...); ``labels`` are the CSP-neutral pre-filter the adapter maps to
    its own label surface. Kept separate so downstream code can compose
    a CSP-neutral filter (labels) with a vendor-specific tail
    (expression) without ever hard-coding the tail.
    """

    expression: str
    labels: Mapping[str, str] = field(default_factory=dict)
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One structured log line."""

    at: datetime
    body: str
    severity: str
    labels: Mapping[str, str] = field(default_factory=dict)


class LogQueryProviderError(RuntimeError):
    """Raised on any unrecoverable provider failure - fail-closed."""


@runtime_checkable
class LogQueryProvider(Protocol):
    """Async iterator over structured log records."""

    def query(self, query: LogQuery) -> AsyncIterator[LogRecord]:
        """Stream records matching ``query`` in chronological order."""
        ...


class NoopLogQueryProvider:
    """Upstream default - empty result for every query."""

    async def query(self, query: LogQuery) -> AsyncIterator[LogRecord]:  # noqa: ARG002 - Protocol conformance
        for _ in ():
            yield _  # pragma: no cover - unreachable


def _as_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC) if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class StaticLogQueryProvider:
    """Deterministic in-memory provider for tests.

    Matching semantics: case-insensitive substring match on ``body`` for
    ``expression``, exact match for every label in ``labels``, ordered
    chronologically by ``at``.
    """

    def __init__(self, records: Sequence[LogRecord]) -> None:
        self._records: tuple[LogRecord, ...] = tuple(sorted(records, key=lambda r: _as_utc(r.at)))

    async def query(self, query: LogQuery) -> AsyncIterator[LogRecord]:
        if query.limit is not None and query.limit <= 0:
            return
        needle = query.expression.strip().casefold() if query.expression else ""
        since_utc = _as_utc(query.since) if query.since is not None else None
        until_utc = _as_utc(query.until) if query.until is not None else None
        matched = 0
        for record in self._records:
            if needle and needle not in record.body.casefold():
                continue
            record_at = _as_utc(record.at)
            if since_utc is not None and record_at < since_utc:
                continue
            if until_utc is not None and record_at > until_utc:
                continue
            if any(record.labels.get(k) != v for k, v in query.labels.items()):
                continue
            yield record
            matched += 1
            if query.limit is not None and matched >= query.limit:
                return


__all__ = [
    "LogQuery",
    "LogQueryProvider",
    "LogQueryProviderError",
    "LogRecord",
    "NoopLogQueryProvider",
    "StaticLogQueryProvider",
]
