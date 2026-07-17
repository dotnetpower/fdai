"""In-memory implementation of the console read-model contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from fdai.delivery.read_api.persistence.read_model_contracts import (
    DEFAULT_LIMIT,
    KPI_AUDIT_SAMPLE_LIMIT,
    AuditItem,
    AuditPage,
    AuditQueryFilters,
    AuditSample,
    DashboardKpi,
    HilQueueItem,
    HilQueuePage,
    IncidentCursor,
    IncidentPage,
    IncidentStatusFilter,
    clamp_limit,
    decode_incident_cursor,
    encode_incident_cursor,
)


def normalized_filter_value(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def audit_item_matches(item: AuditItem, filters: AuditQueryFilters) -> bool:
    entry = item.entry
    if filters.from_seq is not None and item.seq < filters.from_seq:
        return False
    if filters.through_seq is not None and item.seq > filters.through_seq:
        return False
    if filters.mode is not None and item.mode != filters.mode:
        return False
    if filters.action_kind is not None and item.action_kind != filters.action_kind:
        return False
    if filters.tier is not None and str(entry.get("tier", "")).lower() != filters.tier:
        return False
    if filters.outcome is not None and str(entry.get("outcome", "")) != filters.outcome:
        return False
    if filters.vertical is not None:
        vertical = entry.get("vertical", entry.get("category"))
        if normalized_filter_value(vertical) != normalized_filter_value(filters.vertical):
            return False
    if filters.window_days is not None:
        try:
            recorded = datetime.fromisoformat(item.recorded_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if recorded < datetime.now(tz=UTC) - timedelta(days=filters.window_days):
            return False
    return True


def hil_item_pending(item: HilQueueItem, *, now: datetime) -> bool:
    if item.ttl_expires_at is None:
        return True
    try:
        expires_at = datetime.fromisoformat(item.ttl_expires_at.replace("Z", "+00:00"))
        return expires_at.tzinfo is not None and expires_at > now
    except ValueError:
        return False


def hil_search_text(item: HilQueueItem) -> str:
    return " ".join(
        (
            item.approval_id,
            item.action_kind,
            item.target_resource_ref,
            item.event_id,
            item.correlation_id or "",
            item.reason,
            *item.reasons,
            *item.citing_rule_ids,
        )
    ).casefold()


class InMemoryConsoleReadModel:
    """Dict-backed console read model for tests and local development."""

    def __init__(self) -> None:
        self._audit: list[AuditItem] = []
        self._hil: list[HilQueueItem] = []
        self._lock = Lock()
        self._seq = 0

    def record_audit_entry(
        self,
        entry: Mapping[str, Any],
        *,
        actor: str | None = None,
        action_kind: str | None = None,
        mode: str | None = None,
    ) -> AuditItem:
        with self._lock:
            self._seq += 1
            resolved_actor = actor or str(entry.get("actor", "fdai"))
            resolved_kind = action_kind or str(entry.get("action_kind", "unknown"))
            resolved_mode = mode or str(entry.get("mode", "shadow"))
            if resolved_mode not in ("shadow", "enforce"):
                raise ValueError(
                    f"audit entry mode MUST be 'shadow'|'enforce', got {resolved_mode!r}"
                )
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
                recorded_at=str(entry.get("recorded_at") or datetime.now(tz=UTC).isoformat()),
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

    async def list_audit(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        correlation_id: str | None = None,
        filters: AuditQueryFilters | None = None,
    ) -> AuditPage:
        bounded = clamp_limit(limit)
        cutoff = parse_cursor(cursor)
        with self._lock:
            all_items = list(reversed(self._audit))
        if correlation_id is not None:
            from fdai.delivery.read_api.routes.incident_projection import correlate_audit_items

            correlated = correlate_audit_items(reversed(all_items))
            all_items = list(reversed(correlated.get(correlation_id, ())))
        if filters is not None:
            all_items = [item for item in all_items if audit_item_matches(item, filters)]
        if cutoff is not None:
            all_items = [item for item in all_items if item.seq < cutoff]
        page = all_items[:bounded]
        next_cursor = str(page[-1].seq) if len(all_items) > bounded and page else None
        return AuditPage(items=tuple(page), next_cursor=next_cursor)

    async def list_incidents(
        self,
        *,
        status: IncidentStatusFilter = "active",
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        vertical: str | None = None,
        correlation_id: str | None = None,
    ) -> IncidentPage:
        from fdai.delivery.read_api.routes.incident_projection import project_incidents

        bounded = clamp_limit(limit)
        decoded = decode_incident_cursor(cursor, status=status, vertical=vertical)
        with self._lock:
            snapshot_seq = decoded.snapshot_seq if decoded else self._seq
            snapshot = tuple(item for item in self._audit if item.seq <= snapshot_seq)
        summaries = project_incidents(snapshot, status=status)
        if correlation_id is not None:
            summaries = tuple(item for item in summaries if item.correlation_id == correlation_id)
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
            snapshot = list(self._audit[-KPI_AUDIT_SAMPLE_LIMIT:])
            now = datetime.now(tz=UTC)
            hil_pending = sum(1 for item in self._hil if hil_item_pending(item, now=now))
        total = len(snapshot)
        audit_sample = AuditSample(
            from_seq=snapshot[0].seq if snapshot else None,
            through_seq=snapshot[-1].seq if snapshot else None,
            row_count=total,
            limit=KPI_AUDIT_SAMPLE_LIMIT,
        )
        if total == 0:
            return DashboardKpi(0, 0.0, 0.0, hil_pending, audit_sample=audit_sample)
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
                tier_key = str(tier).lower()
                by_tier[tier_key] = by_tier.get(tier_key, 0) + 1
            shadow += item.mode == "shadow"
            enforce += item.mode == "enforce"
        return DashboardKpi(
            event_count=total,
            shadow_share=shadow / total,
            enforce_share=enforce / total,
            hil_pending=hil_pending,
            by_action_kind=by_kind,
            by_outcome=by_outcome,
            by_tier=by_tier,
            last_recorded_at=snapshot[-1].recorded_at,
            audit_sample=audit_sample,
        )

    async def list_hil_queue(
        self, *, limit: int = DEFAULT_LIMIT, search: str | None = None
    ) -> HilQueuePage:
        bounded = clamp_limit(limit)
        with self._lock:
            now = datetime.now(tz=UTC)
            pending = [item for item in self._hil if hil_item_pending(item, now=now)]
            if search:
                needle = search.casefold()
                pending = [item for item in pending if needle in hil_search_text(item)]
            total = len(pending)
            page = list(reversed(pending))[:bounded]
        return HilQueuePage(items=tuple(page), total=total)

    @property
    def audit_items(self) -> Iterable[AuditItem]:
        with self._lock:
            return tuple(self._audit)


def parse_cursor(cursor: str | None) -> int | None:
    if cursor is None or cursor == "":
        return None
    try:
        return int(cursor)
    except ValueError as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


__all__ = ["InMemoryConsoleReadModel"]
