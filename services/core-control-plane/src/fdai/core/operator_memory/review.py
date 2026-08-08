"""Read-only review projection for durable operator memory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.operator_memory.store import OperatorMemoryStore
from fdai.core.operator_memory.types import OperatorMemoryEntry, ScopeKind


@dataclass(frozen=True, slots=True)
class OperatorMemoryReviewItem:
    id: str
    scope_kind: str
    scope_ref: str
    category: str
    body: str
    source_event: str
    source_ref: str
    author: str
    approved_by: str
    approval_state: str
    created_at: str
    expires_at: str | None
    expired: bool
    superseded_by: str | None
    active: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OperatorMemoryReviewService:
    def __init__(
        self,
        *,
        store: OperatorMemoryStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def list(
        self,
        *,
        limit: int = 100,
        scope_kind: ScopeKind | None = None,
        scope_ref: str | None = None,
    ) -> tuple[OperatorMemoryReviewItem, ...]:
        entries = await self._store.list_for_review(
            limit=limit,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
        )
        now = self._clock()
        return tuple(_project(entry, now=now) for entry in entries)


def _project(entry: OperatorMemoryEntry, *, now: datetime) -> OperatorMemoryReviewItem:
    expires_at = (
        entry.created_at + timedelta(seconds=entry.ttl_seconds)
        if entry.ttl_seconds is not None
        else None
    )
    expired = expires_at is not None and now >= expires_at
    superseded = entry.superseded_by is not None
    return OperatorMemoryReviewItem(
        id=str(entry.id),
        scope_kind=entry.scope_kind.value,
        scope_ref=entry.scope_ref,
        category=entry.category.value,
        body=entry.body,
        source_event=entry.source_event.value,
        source_ref=entry.source_ref,
        author=entry.author,
        approved_by=entry.approved_by,
        approval_state="approved",
        created_at=entry.created_at.isoformat(),
        expires_at=expires_at.isoformat() if expires_at is not None else None,
        expired=expired,
        superseded_by=str(entry.superseded_by) if entry.superseded_by is not None else None,
        active=not expired and not superseded,
    )


__all__ = ["OperatorMemoryReviewItem", "OperatorMemoryReviewService"]
