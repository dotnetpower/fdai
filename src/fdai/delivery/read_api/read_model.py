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

import base64
import binascii
import json
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Literal, Protocol, runtime_checkable

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


IncidentStatus = Literal["open", "in_progress", "resolved"]
IncidentStatusFilter = Literal["active", "resolved", "all"]


@dataclass(frozen=True, slots=True)
class AuditQueryFilters:
    """Server-side audit filters applied before cursor pagination."""

    mode: str | None = None
    tier: str | None = None
    action_kind: str | None = None
    outcome: str | None = None
    vertical: str | None = None
    window_days: int | None = None


@dataclass(frozen=True, slots=True)
class IncidentSummary:
    """One durable incident projection keyed by ``correlation_id``."""

    correlation_id: str
    incident_id: str | None
    ticket_id: str | None
    title: str
    severity: str
    status: IncidentStatus
    status_source: str
    disposition: str
    verdict: str
    vertical: str
    opened_at: str
    last_updated_at: str
    latest_mode: str
    history_count: int
    involved_agents: Sequence[str]
    last_seq: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("last_seq")
        return data


@dataclass(frozen=True, slots=True)
class IncidentPage:
    """One page of incident summaries plus an opaque continuation cursor."""

    items: Sequence[IncidentSummary]
    next_cursor: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class IncidentCursor:
    """Decoded incident keyset cursor bound to one immutable audit snapshot."""

    snapshot_seq: int
    before_seq: int
    status: IncidentStatusFilter
    vertical: str | None = None


def encode_incident_cursor(cursor: IncidentCursor) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "snapshot_seq": cursor.snapshot_seq,
            "before_seq": cursor.before_seq,
            "status": cursor.status,
            "vertical": cursor.vertical,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_incident_cursor(
    value: str | None, *, status: IncidentStatusFilter, vertical: str | None = None
) -> IncidentCursor | None:
    if value is None or value == "":
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(raw, dict) or raw.get("v") != 1:
            raise ValueError
        snapshot_seq = raw["snapshot_seq"]
        before_seq = raw["before_seq"]
        cursor_status = raw["status"]
        cursor_vertical = raw.get("vertical")
        if (
            not isinstance(snapshot_seq, int)
            or isinstance(snapshot_seq, bool)
            or snapshot_seq < 0
            or not isinstance(before_seq, int)
            or isinstance(before_seq, bool)
            or before_seq < 1
            or cursor_status != status
            or cursor_vertical != vertical
        ):
            raise ValueError
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid incident cursor or status mismatch") from exc
    return IncidentCursor(
        snapshot_seq=snapshot_seq,
        before_seq=before_seq,
        status=status,
        vertical=vertical,
    )


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
    approval_id: str = ""
    action_id: str = ""
    target_resource_ref: str = ""
    mode: str = ""
    stop_condition: str = ""
    rollback_kind: str = ""
    rollback_reference: str | None = None
    blast_radius_scope: str = ""
    blast_radius_count: int | None = None
    blast_radius_rate_per_minute: int | None = None
    blast_radius_summary: str = ""
    reasons: tuple[str, ...] = ()
    citing_rule_ids: tuple[str, ...] = ()
    ttl_expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "event_id": self.event_id,
            "action_kind": self.action_kind,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "correlation_id": self.correlation_id,
            "approval_id": self.approval_id,
            "action_id": self.action_id,
            "target_resource_ref": self.target_resource_ref,
            "mode": self.mode,
            "stop_condition": self.stop_condition,
            "rollback_kind": self.rollback_kind,
            "rollback_reference": self.rollback_reference,
            "blast_radius_scope": self.blast_radius_scope,
            "blast_radius_count": self.blast_radius_count,
            "blast_radius_rate_per_minute": self.blast_radius_rate_per_minute,
            "blast_radius_summary": self.blast_radius_summary,
            "reasons": list(self.reasons),
            "citing_rule_ids": list(self.citing_rule_ids),
            "ttl_expires_at": self.ttl_expires_at,
        }


@dataclass(frozen=True, slots=True)
class HilQueuePage:
    """One page of pending HIL items."""

    items: Sequence[HilQueueItem]
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items], "total": self.total}


@dataclass(frozen=True, slots=True)
class RcaCitationView:
    """One grounded evidence reference backing an RCA hypothesis.

    Mirrors :class:`fdai.core.rca.contract.Citation` as the console
    renders it. ``ref`` is an opaque id (rule id, event id, metric name,
    scenario id, or ``knowledge:...`` handle) - never a raw payload.
    """

    kind: str
    ref: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True, slots=True)
class RcaCausalHopView:
    """One evidence-bearing edge in a projected RCA causal chain."""

    cause_event_id: str
    effect_event_id: str
    cause_resource_ref: str
    effect_resource_ref: str
    lead_seconds: float
    relationship: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RcaCausalChainView:
    """Structured T1 chain retained by the audit-to-console projection."""

    root_event_id: str
    failure_event_id: str
    confidence: float
    ambiguity: int
    hops: Sequence[RcaCausalHopView]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_event_id": self.root_event_id,
            "failure_event_id": self.failure_event_id,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "hops": [hop.to_dict() for hop in self.hops],
        }


@dataclass(frozen=True, slots=True)
class RcaHypothesisView:
    """One root-cause hypothesis as projected from the audit ledger.

    Sourced from a shadow ``rca.hypothesis`` audit entry (see
    :meth:`fdai.core.control_loop.orchestrator.ControlLoopOrchestrator._analyze_and_audit_rca`).
    An RCA hypothesis is never an authoritative verdict; an ungrounded /
    abstained hypothesis is surfaced explicitly (``grounded == False``,
    ``outcome == "abstained"``) so the console renders it as "insufficient
    grounding -> HIL", never as a confident cause.
    """

    seq: int
    tier: str
    outcome: str
    grounded: bool
    cause: str | None
    confidence: float | None
    reason: str | None
    citations: Sequence[RcaCitationView]
    remediation_ref: str | None
    causal_chain: RcaCausalChainView | None
    mode: str
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tier": self.tier,
            "outcome": self.outcome,
            "grounded": self.grounded,
            "cause": self.cause,
            "confidence": self.confidence,
            "reason": self.reason,
            "citations": [c.to_dict() for c in self.citations],
            "remediation_ref": self.remediation_ref,
            "causal_chain": self.causal_chain.to_dict() if self.causal_chain else None,
            "mode": self.mode,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class RcaResponsePlan:
    """The linked response / remediation plan for one incident.

    Composed from the same correlated audit stream as the RCA
    hypotheses - the risk-gate verdict, the delivered action, its
    shadow-vs-enforce mode, and the rollback reference. The RCA layer
    answers "why"; execution eligibility still belongs to the risk gate
    and verifier, so this is a read-only reflection of what the pipeline
    already decided.
    """

    verdict: str
    decision: str | None
    action_kind: str | None
    mode: str | None
    rollback_reference: str | None
    recorded_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "decision": self.decision,
            "action_kind": self.action_kind,
            "mode": self.mode,
            "rollback_reference": self.rollback_reference,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class RcaView:
    """Per-incident RCA projection: hypotheses plus linked response plan.

    Keyed by ``correlation_id`` (the incident key that threads detection
    -> verdict -> remediation -> audit). Composes existing audit data;
    it introduces no new source of truth.
    """

    correlation_id: str
    incident_id: str | None
    hypotheses: Sequence[RcaHypothesisView]
    response: RcaResponsePlan | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "incident_id": self.incident_id,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "response": self.response.to_dict() if self.response else None,
        }


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
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
        vertical: str | None = None,
    ) -> IncidentPage:
        """Return incident-centric projections, newest activity first."""
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


def _normalized_filter_value(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _audit_item_matches(item: AuditItem, filters: AuditQueryFilters) -> bool:
    entry = item.entry
    if filters.mode is not None and item.mode != filters.mode:
        return False
    if filters.action_kind is not None and item.action_kind != filters.action_kind:
        return False
    if filters.tier is not None and str(entry.get("tier", "")) != filters.tier:
        return False
    if filters.outcome is not None and str(entry.get("outcome", "")) != filters.outcome:
        return False
    if filters.vertical is not None:
        vertical = entry.get("vertical", entry.get("category"))
        if _normalized_filter_value(vertical) != _normalized_filter_value(filters.vertical):
            return False
    if filters.window_days is not None:
        try:
            recorded = datetime.fromisoformat(item.recorded_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if recorded < datetime.now(tz=UTC) - timedelta(days=filters.window_days):
            return False
    return True


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
        correlation_id: str | None = None,
        filters: AuditQueryFilters | None = None,
    ) -> AuditPage:
        bounded = clamp_limit(limit)
        # Cursor is the seq of the last item on the previous page. Newer
        # rows have higher seq; "next page" means strictly smaller seq.
        cutoff = _parse_cursor(cursor)
        with self._lock:
            all_items = list(reversed(self._audit))
        if correlation_id is not None:
            from fdai.delivery.read_api.routes.incident_projection import correlate_audit_items

            correlated = correlate_audit_items(reversed(all_items))
            all_items = list(reversed(correlated.get(correlation_id, ())))
        if filters is not None:
            all_items = [item for item in all_items if _audit_item_matches(item, filters)]
        if cutoff is not None:
            all_items = [i for i in all_items if i.seq < cutoff]
        page = all_items[:bounded]
        next_cursor = str(page[-1].seq) if len(all_items) > bounded and page else None
        return AuditPage(items=tuple(page), next_cursor=next_cursor)

    async def list_incidents(
        self,
        *,
        status: IncidentStatusFilter = "active",
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
        vertical: str | None = None,
    ) -> IncidentPage:
        from fdai.delivery.read_api.routes.incident_projection import project_incidents

        bounded = clamp_limit(limit)
        decoded = decode_incident_cursor(cursor, status=status, vertical=vertical)
        with self._lock:
            snapshot_seq = decoded.snapshot_seq if decoded else self._seq
            snapshot = tuple(item for item in self._audit if item.seq <= snapshot_seq)
        summaries = project_incidents(snapshot, status=status)
        if vertical is not None:
            summaries = tuple(item for item in summaries if item.vertical == vertical)
        if decoded is not None:
            summaries = tuple(item for item in summaries if item.last_seq < decoded.before_seq)
        page = summaries[:bounded]
        next_cursor = (
            encode_incident_cursor(
                IncidentCursor(
                    snapshot_seq=snapshot_seq,
                    before_seq=page[-1].last_seq,
                    status=status,
                    vertical=vertical,
                )
            )
            if len(summaries) > bounded and page
            else None
        )
        return IncidentPage(items=page, next_cursor=next_cursor)

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
