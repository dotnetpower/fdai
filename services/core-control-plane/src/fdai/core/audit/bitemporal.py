"""Bitemporal queries over the audit log.

Every audit entry already carries ``recorded_at`` (system time when the
row landed) and, when the entry represents a resource state, an
``effective_at`` payload field (business time the state took effect).
This module treats the audit log as a bitemporal source-of-truth and
answers **"what did the system know about the state of resource X at
time T?"** with a deterministic query.

Two axes
--------
- ``as_of``   - system time cutoff: only entries with
  ``recorded_at <= as_of`` are considered. Defaults to "now".
- ``effective`` - business time cutoff: from the surviving entries,
  only those with ``effective_at <= effective`` count. Defaults to
  ``as_of`` (the classic "snapshot as of T" question).

The module is a pure projection - it computes the answer from an
injected :class:`~fdai.core.audit.rule_fire_trace.AuditItemLike`
sequence, never mutates the audit store. A fork wires the store
adapter; the query keeps the invariant that the audit trail itself
is append-only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from fdai.core.audit.rule_fire_trace import AuditItemLike


@dataclass(frozen=True, slots=True)
class BitemporalSnapshot:
    """One resource's state as reconstructed from the audit log."""

    resource_id: str
    as_of: datetime
    effective: datetime
    state: Mapping[str, Any]
    source_seqs: tuple[int, ...]
    """Sequence numbers of audit entries that contributed to this state."""

    def as_json(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "as_of": self.as_of.isoformat(),
            "effective": self.effective.isoformat(),
            "state": dict(self.state),
            "source_seqs": list(self.source_seqs),
        }


@runtime_checkable
class BitemporalAuditSource(Protocol):
    """Fork-injected read seam that yields audit items for a resource id."""

    async def read_items(self, resource_id: str) -> Sequence[AuditItemLike]:
        """Return every audit item mentioning ``resource_id``, any order."""
        ...


class BitemporalQueryError(ValueError):
    """Raised on malformed inputs (unparseable timestamps, empty resource id)."""


def snapshot_at(
    resource_id: str,
    items: Iterable[AuditItemLike],
    *,
    as_of: datetime,
    effective: datetime | None = None,
) -> BitemporalSnapshot:
    """Fold ``items`` into a state snapshot at ``as_of`` / ``effective``.

    Fold rule: for each entry surviving BOTH cutoffs, merge its
    ``entry["state"]`` mapping into the running state, using
    ``effective_at`` (or ``recorded_at`` as a fallback) as the tie
    breaker (later-effective wins). Entries without a ``state`` block
    are treated as **audit only** and contribute nothing to the fold
    but still land in ``source_seqs`` for provenance.
    """
    if not resource_id:
        raise BitemporalQueryError("resource_id MUST be non-empty")
    # Normalize the query cutoffs to tz-aware (naive -> UTC). Audit
    # timestamps are written UTC-aware repo-wide, but as_of/effective are
    # caller params with no tz discipline; a naive one would make the
    # comparisons below raise TypeError (offset-naive vs offset-aware)
    # instead of yielding a clean snapshot.
    as_of = _ensure_aware(as_of)
    if effective is None:
        effective = as_of
    effective = _ensure_aware(effective)
    if effective > as_of:
        # Business time in the future of system time makes no sense:
        # we would be asking "what state took effect by <effective>
        # even though the system did not know until <as_of before
        # effective>", i.e. asking the log to predict. Fail-closed.
        raise BitemporalQueryError(
            "effective MUST be <= as_of (bitemporal snapshots do not predict)"
        )

    scored: list[tuple[datetime, int, Mapping[str, Any]]] = []
    provenance: list[int] = []
    for item in items:
        recorded = _parse_ts(item.recorded_at)
        if recorded is None or recorded > as_of:
            continue
        provenance.append(item.seq)
        entry = dict(item.entry)
        effective_ts_raw = entry.get("effective_at") or item.recorded_at
        eff_ts = _parse_ts(effective_ts_raw)
        if eff_ts is None or eff_ts > effective:
            continue
        state = entry.get("state")
        if isinstance(state, Mapping):
            scored.append((eff_ts, item.seq, state))

    scored.sort(key=lambda triple: (triple[0], triple[1]))
    folded: dict[str, Any] = {}
    for _ts, _seq, state in scored:
        folded.update(state)

    return BitemporalSnapshot(
        resource_id=resource_id,
        as_of=as_of,
        effective=effective,
        state=folded,
        source_seqs=tuple(sorted(provenance)),
    )


def _ensure_aware(dt: datetime) -> datetime:
    """Coerce a naive datetime to UTC (the repo-wide convention).

    Keeps every bitemporal comparison offset-aware so a naive cutoff or a
    naive ``effective_at`` written by a fork adapter cannot raise
    ``TypeError`` mid-fold.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _parse_ts(raw: str | datetime | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _ensure_aware(raw)
    try:
        return _ensure_aware(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except ValueError:
        return None


__all__ = [
    "BitemporalAuditSource",
    "BitemporalQueryError",
    "BitemporalSnapshot",
    "snapshot_at",
]
