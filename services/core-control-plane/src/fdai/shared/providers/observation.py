"""Observation-depth Protocols - Wave M1.5.

Three CSP-neutral seams the operator console's Month-1 read-class tools
consume (see
[operator-console.md](../../../../docs/roadmap/interfaces/operator-console.md)
section 3.3 on Month-1 additions):

- :class:`LogQueryProvider` - Log Analytics-shaped KQL queries
  (``query_log``).
- :class:`MetricQueryProvider` - Metrics API (``query_metric``).
- :class:`DeploymentHistoryProvider` - deployment-history join
  (``query_deployments``).

The fourth Month-1 tool (``correlate_incident``) is layered above these
three via :class:`IncidentCorrelator`; the correlator uses the three
providers plus ``event_ingest`` internally.

Design invariants
-----------------

- **Read-only, bounded**: every method is a bounded query that returns
  in a bounded window. No streaming, no write.
- **CSP-neutral shape**: the query string is opaque to ``core/``; the
  adapter interprets it. This keeps ``core/`` free of vendor SDKs.
- **Abstain-safe**: an adapter that cannot answer (missing scope,
  unauthorized, transport failure) raises a domain-specific error the
  caller converts into an ``abstain`` narrator response.
- **No privileged identity in ``core/``**: real adapters (Azure
  Monitor, deployment history) live in ``delivery/azure/`` and are
  fork-authored; upstream ships Protocols + fakes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ObservationError(RuntimeError):
    """Base error for every observation-depth adapter."""


class LogQueryError(ObservationError):
    """Raised by :class:`LogQueryProvider` on transport / auth / query failure."""


class MetricQueryError(ObservationError):
    """Raised by :class:`MetricQueryProvider` on transport / auth failure."""


class DeploymentHistoryError(ObservationError):
    """Raised by :class:`DeploymentHistoryProvider` on transport / auth failure."""


class IncidentCorrelationError(ObservationError):
    """Raised by :class:`IncidentCorrelator` when correlation abstains."""


@dataclass(frozen=True, slots=True)
class LogQueryResult:
    """Result of one :meth:`LogQueryProvider.query_log` call.

    ``rows`` is opaque to ``core/`` - each entry is a mapping the
    adapter produced. Callers project the fields they need.
    """

    rows: tuple[Mapping[str, Any], ...]
    truncated: bool = False
    scanned_records: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """One (timestamp, value) datapoint for a metric aggregation."""

    timestamp: str
    value: float


@dataclass(frozen=True, slots=True)
class MetricQueryResult:
    """Result of one :meth:`MetricQueryProvider.query_metric` call."""

    namespace: str
    metric: str
    aggregation: str
    points: tuple[MetricPoint, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    """One row in a deployment-history result set.

    CSP-neutral: ``deployment_ref`` is opaque (Git SHA, ARM deployment
    id, PR reference); ``resource_refs`` are inventory refs.
    """

    deployment_ref: str
    timestamp: str
    author: str
    resource_refs: tuple[str, ...]
    status: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeploymentHistoryResult:
    """Result of one :meth:`DeploymentHistoryProvider.query_deployments` call."""

    records: tuple[DeploymentRecord, ...]
    window: str


@dataclass(frozen=True, slots=True)
class IncidentCorrelation:
    """Result of one :meth:`IncidentCorrelator.correlate` call.

    Every field is populated even when empty so a caller can rely on
    the shape (an empty tuple means "no signal", not "unknown").
    """

    incident_id: str
    events: tuple[Mapping[str, Any], ...]
    audit_entries: tuple[Mapping[str, Any], ...]
    log_hits: tuple[Mapping[str, Any], ...]
    metric_points: tuple[MetricPoint, ...]
    deployments: tuple[DeploymentRecord, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol seams
# ---------------------------------------------------------------------------


@runtime_checkable
class LogQueryProvider(Protocol):
    """Read-only, bounded KQL-shaped log query.

    Real adapters run the query against Log Analytics / a fork's log
    store. The upstream ships this Protocol + an in-memory fake.
    """

    async def query_log(
        self,
        *,
        query: str,
        window: str,
        max_rows: int = 100,
    ) -> LogQueryResult:
        """Run ``query`` over ``window`` and return up to ``max_rows`` rows.

        MUST fail-closed on a policy / transport error by raising
        :class:`LogQueryError`; the caller converts a raise into an
        ``abstain`` narrator response.
        """
        ...


@runtime_checkable
class MetricQueryProvider(Protocol):
    """Read-only metric aggregation query."""

    async def query_metric(
        self,
        *,
        namespace: str,
        metric: str,
        aggregation: str,
        window: str,
    ) -> MetricQueryResult:
        """Return an aggregation timeseries.

        MUST fail-closed by raising :class:`MetricQueryError`.
        """
        ...


@runtime_checkable
class DeploymentHistoryProvider(Protocol):
    """Read-only deployment-history query.

    Joins Git commits + IaC deployments so the caller sees "what changed
    in the estate over the window".
    """

    async def query_deployments(
        self,
        *,
        window: str,
        resource_ref: str | None = None,
    ) -> DeploymentHistoryResult:
        """Return every deployment in ``window`` (optionally filtered).

        MUST fail-closed by raising :class:`DeploymentHistoryError`.
        """
        ...


@runtime_checkable
class IncidentCorrelator(Protocol):
    """Multi-signal correlation over ``event_ingest`` + audit + logs +
    metrics + deployments for one incident id.

    The correlator lives in Layer 1 (the operator console never runs
    the correlation itself), so this Protocol is a thin bridge that
    lets the console surface an already-computed result.
    """

    async def correlate(self, *, incident_id: str) -> IncidentCorrelation:
        """Return a correlated view of every signal for ``incident_id``.

        MUST raise :class:`IncidentCorrelationError` when the correlator
        cannot ground an answer (unknown incident id, adapter failure).
        """
        ...


__all__ = [
    "DeploymentHistoryError",
    "DeploymentHistoryProvider",
    "DeploymentHistoryResult",
    "DeploymentRecord",
    "IncidentCorrelation",
    "IncidentCorrelationError",
    "IncidentCorrelator",
    "LogQueryError",
    "LogQueryProvider",
    "LogQueryResult",
    "MetricPoint",
    "MetricQueryError",
    "MetricQueryProvider",
    "MetricQueryResult",
    "ObservationError",
]
