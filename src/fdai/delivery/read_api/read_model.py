"""Read-only projection surface for the console SPA.

The console has three views (KPI dashboard, audit log, HIL queue) - each
one is one GET call. Rather than let handlers reach directly into the
:class:`~fdai.shared.providers.state_store.StateStore` (which knows
only how to *append* audit entries), this module defines a narrow
**read model Protocol** that a fork's composition root binds to a concrete
implementation (e.g. a Postgres-backed adapter). The upstream repo ships:

- :class:`ConsoleReadModel` - the Protocol,
- :class:`InMemoryConsoleReadModel` - a dev / test fake that also drives
  the pytest suite.

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

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol, runtime_checkable

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class AuditItem:
    """One row of the audit log as the console renders it.

    Fields intentionally mirror the persisted ``audit_log`` row (see
    ``alembic/versions/20260705_0001_base.py``) with the JSON payload
    kept as an opaque ``entry`` map - the console renders it with a
    generic key/value viewer, so the API is stable across schema
    additions.
    """

    seq: int
    event_id: str
    correlation_id: str | None
    actor: str
    action_kind: str
    mode: str
    entry: Mapping[str, Any]
    entry_hash: str
    previous_hash: str
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serializable form suitable for :class:`starlette.responses.JSONResponse`."""
        return {
            "seq": self.seq,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "actor": self.actor,
            "action_kind": self.action_kind,
            "mode": self.mode,
            "entry": dict(self.entry),
            "entry_hash": self.entry_hash,
            "previous_hash": self.previous_hash,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class AuditPage:
    """One page of audit items plus a cursor for the next page (or ``None``)."""

    items: Sequence[AuditItem]
    next_cursor: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class DashboardKpi:
    """KPI dashboard aggregates derived from the audit stream.

    Fields track the surface the console renders. Ratios are in
    ``[0, 1]``; ``event_count`` is the sample-size denominator.
    ``by_action_kind`` / ``by_outcome`` / ``by_tier`` are simple counts
    keyed by the audit entry's ``action_kind``, ``outcome``, and ``tier``
    fields; entries without a ``tier`` are omitted from ``by_tier``.
    """

    event_count: int
    shadow_share: float
    enforce_share: float
    hil_pending: int
    by_action_kind: Mapping[str, int] = field(default_factory=dict)
    by_outcome: Mapping[str, int] = field(default_factory=dict)
    by_tier: Mapping[str, int] = field(default_factory=dict)
    last_recorded_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["by_action_kind"] = dict(self.by_action_kind)
        data["by_outcome"] = dict(self.by_outcome)
        data["by_tier"] = dict(self.by_tier)
        return data


@dataclass(frozen=True, slots=True)
class HilQueueItem:
    """One pending HIL approval item.

    The console renders these as an alert list; approval happens through
    ChatOps (Teams Adaptive Card) - the console MUST NOT expose a "Approve"
    button (see app-shape.instructions.md § Layer Boundaries).
    """

    idempotency_key: str
    event_id: str
    action_kind: str
    reason: str
    requested_at: str
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "event_id": self.event_id,
            "action_kind": self.action_kind,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, slots=True)
class HilQueuePage:
    """One page of pending HIL items."""

    items: Sequence[HilQueueItem]
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items], "total": self.total}


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
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> AuditPage:
        """Return one page of audit items, newest first.

        ``limit`` MUST be clamped by the implementation to a sensible
        ceiling (see :data:`MAX_LIMIT`). ``cursor`` is opaque; a caller
        MUST NOT parse it.
        """
        ...

    async def dashboard_metrics(self) -> DashboardKpi:
        """Return the KPI snapshot."""
        ...

    async def list_hil_queue(self, *, limit: int = _DEFAULT_LIMIT) -> HilQueuePage:
        """Return the pending HIL items (newest first)."""
        ...


def clamp_limit(limit: int | None) -> int:
    """Bound the ``?limit=`` query param to ``[1, MAX_LIMIT]``.

    Exposed as module-level so both the Protocol implementations and the
    HTTP handlers use the same clamp - a driver-side ``limit=99999`` MUST
    never turn into an unbounded scan.
    """
    if limit is None:
        return _DEFAULT_LIMIT
    if limit < 1:
        return 1
    if limit > _MAX_LIMIT:
        return _MAX_LIMIT
    return limit


MAX_LIMIT = _MAX_LIMIT
DEFAULT_LIMIT = _DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# In-memory fake - powers the pytest suite and (optionally) the local dev
# harness so a developer can `python -m fdai.delivery.read_api` and
# hit the console without a live Postgres.
# ---------------------------------------------------------------------------


class InMemoryConsoleReadModel(ConsoleReadModel):
    """Dict-backed :class:`ConsoleReadModel` for tests + local dev.

    Not suitable for production - entries vanish on process restart.
    Adds :meth:`record_audit_entry` and :meth:`record_hil_pending` so
    tests can seed the model without a full control-loop replay.
    """

    def __init__(self) -> None:
        self._audit: list[AuditItem] = []
        self._hil: list[HilQueueItem] = []
        self._lock = Lock()
        self._seq = 0

    # ------------------------------------------------------------------
    # Test seeding helpers
    # ------------------------------------------------------------------

    def record_audit_entry(
        self,
        entry: Mapping[str, Any],
        *,
        actor: str | None = None,
        action_kind: str | None = None,
        mode: str | None = None,
    ) -> AuditItem:
        """Append one audit item using the persisted schema's field names.

        Missing top-level fields fall back to sensible defaults so tests
        can pass minimal fixtures. The audit hash chain is NOT enforced
        here - the fake exists to drive the HTTP surface, not to mirror
        :class:`~fdai.shared.providers.testing.state_store.InMemoryStateStore`.
        """
        with self._lock:
            self._seq += 1
            resolved_actor = actor or str(entry.get("actor", "fdai"))
            resolved_kind = action_kind or str(entry.get("action_kind", "unknown"))
            resolved_mode = mode or str(entry.get("mode", "shadow"))
            if resolved_mode not in ("shadow", "enforce"):
                raise ValueError(
                    f"audit entry mode MUST be 'shadow'|'enforce', got {resolved_mode!r}"
                )
            recorded_at = str(entry.get("recorded_at") or datetime.now(tz=UTC).isoformat())
            item = AuditItem(
                seq=self._seq,
                event_id=str(entry.get("event_id", "00000000-0000-0000-0000-000000000000")),
                correlation_id=(
                    str(entry["correlation_id"])
                    if entry.get("correlation_id") is not None
                    else None
                ),
                actor=resolved_actor,
                action_kind=resolved_kind,
                mode=resolved_mode,
                entry=deepcopy(dict(entry)),
                entry_hash=f"stub-{self._seq:016x}",
                previous_hash=(self._audit[-1].entry_hash if self._audit else "0" * 64),
                recorded_at=recorded_at,
            )
            self._audit.append(item)
            return item

    def record_hil_pending(self, item: HilQueueItem) -> None:
        with self._lock:
            self._hil.append(item)

    def clear(self) -> None:
        with self._lock:
            self._audit.clear()
            self._hil.clear()
            self._seq = 0

    # ------------------------------------------------------------------
    # ConsoleReadModel Protocol
    # ------------------------------------------------------------------

    async def list_audit(
        self,
        *,
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> AuditPage:
        bounded = clamp_limit(limit)
        # Cursor is the seq of the last item on the previous page. Newer
        # rows have higher seq; "next page" means strictly smaller seq.
        cutoff = _parse_cursor(cursor)
        with self._lock:
            all_items = list(reversed(self._audit))
        if cutoff is not None:
            all_items = [i for i in all_items if i.seq < cutoff]
        page = all_items[:bounded]
        next_cursor = str(page[-1].seq) if len(all_items) > bounded and page else None
        return AuditPage(items=tuple(page), next_cursor=next_cursor)

    async def dashboard_metrics(self) -> DashboardKpi:
        with self._lock:
            snapshot = list(self._audit)
            hil_pending = len(self._hil)
        total = len(snapshot)
        if total == 0:
            return DashboardKpi(
                event_count=0,
                shadow_share=0.0,
                enforce_share=0.0,
                hil_pending=hil_pending,
                by_action_kind={},
                by_outcome={},
                by_tier={},
                last_recorded_at=None,
            )
        by_kind: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        shadow = 0
        enforce = 0
        for item in snapshot:
            by_kind[item.action_kind] = by_kind.get(item.action_kind, 0) + 1
            outcome = str(item.entry.get("outcome", "unknown"))
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
            tier = item.entry.get("tier")
            if tier is not None:
                tier_key = str(tier)
                by_tier[tier_key] = by_tier.get(tier_key, 0) + 1
            if item.mode == "shadow":
                shadow += 1
            elif item.mode == "enforce":
                enforce += 1
        return DashboardKpi(
            event_count=total,
            shadow_share=shadow / total,
            enforce_share=enforce / total,
            hil_pending=hil_pending,
            by_action_kind=by_kind,
            by_outcome=by_outcome,
            by_tier=by_tier,
            last_recorded_at=snapshot[-1].recorded_at,
        )

    async def list_hil_queue(self, *, limit: int = _DEFAULT_LIMIT) -> HilQueuePage:
        bounded = clamp_limit(limit)
        with self._lock:
            total = len(self._hil)
            page = list(reversed(self._hil))[:bounded]
        return HilQueuePage(items=tuple(page), total=total)

    # ------------------------------------------------------------------
    # Test observability
    # ------------------------------------------------------------------

    @property
    def audit_items(self) -> Iterable[AuditItem]:
        with self._lock:
            return tuple(self._audit)


def _parse_cursor(cursor: str | None) -> int | None:
    if cursor is None or cursor == "":
        return None
    try:
        return int(cursor)
    except ValueError as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "AuditItem",
    "AuditPage",
    "ConsoleReadModel",
    "DashboardKpi",
    "HilQueueItem",
    "HilQueuePage",
    "InMemoryConsoleReadModel",
    "clamp_limit",
]
