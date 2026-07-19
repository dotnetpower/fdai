"""Read-only projection surface for the console SPA.

The console has three views (KPI dashboard, audit log, HIL queue) - each
one is one GET call. Rather than let handlers reach directly into the
:class:`~fdai.shared.providers.state_store.StateStore` (which knows
only how to *append* audit entries), this module defines a narrow
**read model Protocol** that a fork's composition root binds to a concrete
implementation (e.g. a Postgres-backed adapter). The upstream repo ships:

- :class:`ConsoleReadModel` - the Protocol,
- :class:`InMemoryConsoleReadModel` - a test fake. The Azure-only local
    factory may use it empty when no FDAI Azure state plane is deployed, but
    interactive code never seeds it or presents it as observed Azure state.

The Protocol is intentionally colocated with the read-API delivery layer
(not under ``shared/providers/``) because it is a **console-facing view
contract**, not one of the five CSP-neutral wire-level seams. It never
mutates state; it never leaks secrets; the HTTP layer just serializes
what it returns.

Contract highlights (see docs/roadmap/interfaces/user-rbac-and-identity.md § 6):

- Every method is async - real backends (Postgres) block the loop.
- Cursor pagination is opaque: callers pass whatever the previous page
  returned as ``next_cursor``. The Protocol makes no guarantee about the
  cursor's structure other than "treat it as an opaque string".
- Every method MUST return read-only shapes - no callable back-channel
  the console could use to mutate state.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fdai.delivery.read_api.persistence.in_memory_read_model import (
    InMemoryConsoleReadModel as _InMemoryConsoleReadModel,
)
from fdai.delivery.read_api.persistence.rca_contracts import (
    RcaCausalChainView,
    RcaCausalHopView,
    RcaCitationView,
    RcaHypothesisView,
    RcaResponsePlan,
    RcaView,
)
from fdai.delivery.read_api.persistence.read_model_contracts import (
    DEFAULT_LIMIT,
    KPI_AUDIT_SAMPLE_LIMIT,
    MAX_LIMIT,
    AuditItem,
    AuditPage,
    AuditQueryFilters,
    AuditSample,
    DashboardKpi,
    HilQueueItem,
    HilQueuePage,
    IncidentCursor,
    IncidentPage,
    IncidentStatus,
    IncidentStatusFilter,
    IncidentSummary,
    clamp_limit,
    decode_incident_cursor,
    encode_incident_cursor,
)


@runtime_checkable
class ConsoleReadModel(Protocol):
    """Read-only projection of state the console renders.

    Wired at the composition root; the read-API handlers depend only on
    this Protocol so tests can swap in :class:`InMemoryConsoleReadModel`
    without spinning up Postgres.
    """

    async def list_audit(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        correlation_id: str | None = None,
        filters: AuditQueryFilters | None = None,
    ) -> AuditPage:
        """Return one page of audit items, newest first.

        ``limit`` MUST be clamped by the implementation to a sensible
        ceiling (see :data:`MAX_LIMIT`). ``cursor`` is opaque; a caller
        MUST NOT parse it.
        """
        ...

    async def list_incidents(
        self,
        *,
        status: IncidentStatusFilter = "active",
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        vertical: str | None = None,
        correlation_id: str | None = None,
    ) -> IncidentPage:
        """Return incident-centric projections, newest activity first."""
        ...

    async def dashboard_metrics(self) -> DashboardKpi:
        """Return the KPI snapshot."""
        ...

    async def list_hil_queue(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        search: str | None = None,
    ) -> HilQueuePage:
        """Return the pending HIL items (newest first)."""
        ...


class InMemoryConsoleReadModel(_InMemoryConsoleReadModel, ConsoleReadModel):
    """Dict-backed :class:`ConsoleReadModel` for tests and empty local state.

    Not suitable for production - entries vanish on process restart.
    Adds :meth:`record_audit_entry` and :meth:`record_hil_pending` so
    tests can seed the model without a full control-loop replay. Interactive
    local composition MUST leave it empty.
    """

    pass


__all__ = [
    "DEFAULT_LIMIT",
    "KPI_AUDIT_SAMPLE_LIMIT",
    "MAX_LIMIT",
    "AuditItem",
    "AuditPage",
    "AuditQueryFilters",
    "AuditSample",
    "ConsoleReadModel",
    "DashboardKpi",
    "HilQueueItem",
    "HilQueuePage",
    "InMemoryConsoleReadModel",
    "IncidentCursor",
    "IncidentPage",
    "IncidentStatus",
    "IncidentStatusFilter",
    "IncidentSummary",
    "RcaCausalChainView",
    "RcaCausalHopView",
    "RcaCitationView",
    "RcaHypothesisView",
    "RcaResponsePlan",
    "RcaView",
    "clamp_limit",
    "decode_incident_cursor",
    "encode_incident_cursor",
]
