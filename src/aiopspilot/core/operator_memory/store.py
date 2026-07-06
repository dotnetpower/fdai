"""Store Protocol + in-memory implementation for operator memory.

The Postgres-backed store lands in Wave 3 step B alongside the
alembic migration; step A ships the seam and a deterministic
in-memory implementation so the composer integration (Wave 3 step C)
can be built and tested without any database dependency.

Every write path runs :func:`_reject_policy_violations` first so the
Human Override policy (scope <= resource-group, distinct approver,
non-empty body, no injection markers) is enforced at the boundary,
not deep inside the composer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from aiopspilot.core.operator_memory.sanitizer import (
    InjectionMarkerError,
    detect_injection_markers,
)
from aiopspilot.core.operator_memory.types import (
    OperatorMemoryEntry,
    ScopeKind,
)


class OperatorMemoryPolicyError(ValueError):
    """Raised when an entry violates the write-time policy contract.

    Structured as one class so callers can dispatch on ``code`` for
    telemetry without pattern-matching on error messages.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code: Final[str] = code
        super().__init__(f"{code}: {message}")


class OperatorMemoryStore(Protocol):
    """Read/write surface consumed by the HIL pipeline and the composer.

    Every mutating method is async so a Postgres-backed implementation
    can slot in without changing callers. The store is append-only:
    :meth:`supersede` never mutates the referenced entry's body, only
    threads the ``superseded_by`` pointer so a reader sees the newer
    row instead.
    """

    async def append(self, entry: OperatorMemoryEntry) -> OperatorMemoryEntry:
        """Persist ``entry`` after policy validation.

        Returns the stored entry (typically identical to the input)
        so a caller does not need to keep a reference to the input
        object separately.
        """

    async def list_active_for_scope(
        self, *, scope_kind: ScopeKind, scope_ref: str
    ) -> tuple[OperatorMemoryEntry, ...]:
        """Return every non-superseded, non-expired entry matching the
        exact ``(scope_kind, scope_ref)``.

        Scope hierarchy resolution (resource inherits from parent
        resource-group) is the caller's responsibility - the store
        stays flat so the semantics of "active" are unambiguous.
        """

    async def supersede(self, *, entry_id: UUID, superseded_by: UUID) -> None:
        """Mark ``entry_id`` as superseded by a later entry.

        Raises :class:`LookupError` when the id is unknown.
        """


@dataclass(frozen=True, slots=True)
class _Node:
    """Internal wrapper mirrors ``OperatorMemoryEntry`` but is mutable
    only via :func:`dataclasses.replace` so append-only semantics are
    guarded structurally."""

    entry: OperatorMemoryEntry


class InMemoryOperatorMemoryStore(OperatorMemoryStore):
    """Deterministic in-memory store for tests and Wave 3 step A wiring.

    Uses a list-of-nodes with per-id lookups instead of a plain dict
    so the ordering the append log produces is preserved for
    reproducible replay in tests.
    """

    def __init__(self, *, now_fn: Callable[[], datetime] | None = None) -> None:
        # Explicit clock injection keeps the TTL check deterministic
        # under freezegun-style test fixtures. When left as ``None``
        # we call ``datetime.now(tz=UTC)`` directly.
        self._nodes: list[_Node] = []
        self._by_id: dict[UUID, int] = {}
        self._now_fn = now_fn

    async def append(self, entry: OperatorMemoryEntry) -> OperatorMemoryEntry:
        _reject_policy_violations(entry)
        if entry.id in self._by_id:
            raise OperatorMemoryPolicyError(
                "duplicate_id",
                f"entry {entry.id} already exists in the store",
            )
        self._nodes.append(_Node(entry=entry))
        self._by_id[entry.id] = len(self._nodes) - 1
        return entry

    async def list_active_for_scope(
        self, *, scope_kind: ScopeKind, scope_ref: str
    ) -> tuple[OperatorMemoryEntry, ...]:
        now = self._now()
        active: list[OperatorMemoryEntry] = []
        for node in self._nodes:
            entry = node.entry
            if entry.scope_kind is not scope_kind:
                continue
            if entry.scope_ref != scope_ref:
                continue
            if entry.superseded_by is not None:
                continue
            if _is_expired(entry, now=now):
                continue
            active.append(entry)
        return tuple(active)

    async def supersede(self, *, entry_id: UUID, superseded_by: UUID) -> None:
        idx = self._by_id.get(entry_id)
        if idx is None:
            raise LookupError(f"operator memory entry {entry_id} not found")
        existing = self._nodes[idx].entry
        if existing.superseded_by is not None:
            raise OperatorMemoryPolicyError(
                "already_superseded",
                f"entry {entry_id} is already superseded by {existing.superseded_by}",
            )
        replacement = replace(existing, superseded_by=superseded_by)
        self._nodes[idx] = _Node(entry=replacement)

    def _now(self) -> datetime:
        if self._now_fn is None:
            return datetime.now(tz=UTC)
        return self._now_fn()

    # -- iteration helper used by tests only ------------------------------

    def _iter_all_entries(self) -> Iterator[OperatorMemoryEntry]:  # pragma: no cover - test helper
        for node in self._nodes:
            yield node.entry


def _reject_policy_violations(entry: OperatorMemoryEntry) -> None:
    """Enforce every write-time invariant in one place.

    The policy MUST live at the boundary because callers include the
    HIL approval workflow, a future ChatOps ingestion path, and any
    fork-authored source. Repeating the check in each call-site would
    guarantee a case is missed.
    """

    if not entry.body or not entry.body.strip():
        raise OperatorMemoryPolicyError(
            "empty_body",
            "operator memory body MUST be non-empty and non-whitespace",
        )
    if not entry.scope_ref or not entry.scope_ref.strip():
        raise OperatorMemoryPolicyError(
            "empty_scope_ref",
            "operator memory scope_ref MUST be non-empty",
        )
    # ``ScopeKind`` already forbids values broader than resource-group,
    # but a defensive check keeps a future enum extension from silently
    # widening the policy.
    if entry.scope_kind not in (ScopeKind.RESOURCE_GROUP, ScopeKind.RESOURCE):
        raise OperatorMemoryPolicyError(
            "scope_too_wide",
            f"scope_kind {entry.scope_kind!r} is broader than resource-group; "
            "use the rule-catalog retirement pipeline instead",
        )
    if not entry.author or not entry.author.strip():
        raise OperatorMemoryPolicyError(
            "missing_author",
            "operator memory author MUST be non-empty",
        )
    if not entry.approved_by or not entry.approved_by.strip():
        raise OperatorMemoryPolicyError(
            "missing_approver",
            "operator memory approved_by MUST be non-empty (no unreviewed writes)",
        )
    if entry.author.strip().lower() == entry.approved_by.strip().lower():
        raise OperatorMemoryPolicyError(
            "self_approval",
            "author and approved_by MUST be distinct principals",
        )
    if entry.ttl_seconds is not None and entry.ttl_seconds <= 0:
        raise OperatorMemoryPolicyError(
            "invalid_ttl",
            f"ttl_seconds {entry.ttl_seconds!r} MUST be positive or None",
        )
    markers = detect_injection_markers(entry.body)
    if markers:
        # Wrap the sanitizer's exception in the store's policy error so
        # every write-time failure surfaces the same base class.
        raise InjectionMarkerError(markers)


def _is_expired(entry: OperatorMemoryEntry, *, now: datetime) -> bool:
    if entry.ttl_seconds is None:
        return False
    return now - entry.created_at >= timedelta(seconds=entry.ttl_seconds)


__all__ = [
    "InMemoryOperatorMemoryStore",
    "OperatorMemoryPolicyError",
    "OperatorMemoryStore",
]
