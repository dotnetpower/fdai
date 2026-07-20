"""Access-scoped continuation anchors for scheduled results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Never, Protocol

from fdai.core.working_context.types import EntryKind, EntryRole, TranscriptEntry
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationAudience,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledConversationAnchorStore,
    ScheduledResultOrigin,
    anchor_id_for_run,
    scheduled_result_fact_text,
)
from fdai.shared.providers.state_store import StateStore

_MAX_ID = 256


class ContinuationAuditKind(StrEnum):
    CREATED = "created"
    ACCESS_DENIED = "access_denied"
    CONTINUED = "continued"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ContinuationAccess:
    principal_id: str
    authorized_scope_refs: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _identifier("principal_id", self.principal_id)
        for scope_ref in self.authorized_scope_refs:
            _identifier("authorized_scope_ref", scope_ref)


@dataclass(frozen=True, slots=True)
class ContinuationAuditEvent:
    kind: ContinuationAuditKind
    anchor_id: str
    principal_id: str
    at: datetime


class ContinuationAccessDeniedError(PermissionError):
    """Fail closed without revealing whether an anchor exists."""


class ContinuationAuditSink(Protocol):
    async def append(self, event: ContinuationAuditEvent) -> None: ...


class InMemoryScheduledConversationAnchorStore:
    """Process-local mirror of immutable create and CAS expiry semantics."""

    def __init__(self) -> None:
        self._anchors: dict[str, ScheduledConversationAnchor] = {}
        self._run_ids: dict[str, str] = {}

    async def create(self, anchor: ScheduledConversationAnchor) -> ScheduledConversationAnchor:
        existing_id = self._run_ids.get(anchor.run_id)
        if existing_id is not None:
            existing_for_run = self._anchors[existing_id]
            if existing_for_run != anchor:
                raise ValueError("scheduled run already has a different continuation anchor")
            return existing_for_run
        existing_for_anchor = self._anchors.get(anchor.anchor_id)
        if existing_for_anchor is not None and existing_for_anchor != anchor:
            raise ValueError("continuation anchor id conflicts with an existing record")
        self._anchors[anchor.anchor_id] = anchor
        self._run_ids[anchor.run_id] = anchor.anchor_id
        return anchor

    async def get(self, anchor_id: str) -> ScheduledConversationAnchor | None:
        return self._anchors.get(anchor_id)

    async def expire(
        self, *, anchor_id: str, expected_state: ContinuationAnchorState
    ) -> ScheduledConversationAnchor | None:
        current = self._anchors.get(anchor_id)
        if current is None or current.state is not expected_state:
            return current
        expired = replace(current, state=ContinuationAnchorState.EXPIRED)
        self._anchors[anchor_id] = expired
        return expired

    async def list_for_principal(
        self, *, principal_id: str, limit: int = 100
    ) -> tuple[ScheduledConversationAnchor, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        anchors = [
            anchor for anchor in self._anchors.values() if anchor.owner_principal_id == principal_id
        ]
        anchors.sort(key=lambda item: (item.created_at, item.anchor_id), reverse=True)
        return tuple(anchors[:limit])


class InMemoryContinuationAuditSink:
    def __init__(self) -> None:
        self.events: list[ContinuationAuditEvent] = []

    async def append(self, event: ContinuationAuditEvent) -> None:
        self.events.append(event)


class StateStoreContinuationAuditSink:
    """Append continuation lifecycle events to the existing hash-chained audit log."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def append(self, event: ContinuationAuditEvent) -> None:
        await self._store.append_audit_entry(
            {
                "event_type": f"scheduled_continuation.{event.kind.value}",
                "anchor_id": event.anchor_id,
                "principal_id": event.principal_id,
                "recorded_at": event.at.isoformat(),
                "idempotency_key": (
                    f"scheduled-continuation:{event.kind.value}:{event.anchor_id}:"
                    f"{event.principal_id}:{event.at.isoformat()}"
                ),
            }
        )


class ScheduledContinuationService:
    """Create and resolve anchors without treating possession as authorization."""

    def __init__(
        self,
        *,
        store: ScheduledConversationAnchorStore,
        audit: ContinuationAuditSink,
    ) -> None:
        self._store = store
        self._audit = audit

    async def create(self, anchor: ScheduledConversationAnchor) -> ScheduledConversationAnchor:
        stored = await self._store.create(anchor)
        await self._record(
            ContinuationAuditKind.CREATED,
            stored.anchor_id,
            stored.owner_principal_id,
            stored.created_at,
        )
        return stored

    async def resolve(
        self,
        *,
        anchor_id: str,
        access: ContinuationAccess,
        now: datetime,
    ) -> ScheduledConversationAnchor:
        _identifier("anchor_id", anchor_id)
        _aware("now", now)
        anchor = await self._store.get(anchor_id)
        if anchor is None:
            await self._deny(anchor_id, access.principal_id, now)
        if anchor.state is ContinuationAnchorState.EXPIRED or now >= anchor.expires_at:
            if anchor.state is ContinuationAnchorState.ACTIVE:
                await self._store.expire(
                    anchor_id=anchor.anchor_id,
                    expected_state=ContinuationAnchorState.ACTIVE,
                )
                await self._record(
                    ContinuationAuditKind.EXPIRED,
                    anchor.anchor_id,
                    access.principal_id,
                    now,
                )
            await self._deny(anchor.anchor_id, access.principal_id, now)
        if (
            access.principal_id != anchor.owner_principal_id
            and anchor.scope_ref not in access.authorized_scope_refs
        ):
            await self._deny(anchor.anchor_id, access.principal_id, now)
        await self._record(
            ContinuationAuditKind.CONTINUED,
            anchor.anchor_id,
            access.principal_id,
            now,
        )
        return anchor

    async def expire(
        self,
        *,
        anchor_id: str,
        access: ContinuationAccess,
        now: datetime,
    ) -> ScheduledConversationAnchor:
        anchor = await self.resolve(anchor_id=anchor_id, access=access, now=now)
        expired = await self._store.expire(
            anchor_id=anchor.anchor_id,
            expected_state=ContinuationAnchorState.ACTIVE,
        )
        if expired is None:
            raise RuntimeError("scheduled continuation disappeared during expiry")
        await self._record(
            ContinuationAuditKind.EXPIRED,
            anchor.anchor_id,
            access.principal_id,
            now,
        )
        return expired

    async def _deny(self, anchor_id: str, principal_id: str, at: datetime) -> Never:
        await self._record(ContinuationAuditKind.ACCESS_DENIED, anchor_id, principal_id, at)
        raise ContinuationAccessDeniedError("scheduled continuation is unavailable")

    async def _record(
        self,
        kind: ContinuationAuditKind,
        anchor_id: str,
        principal_id: str,
        at: datetime,
    ) -> None:
        await self._audit.append(
            ContinuationAuditEvent(
                kind=kind,
                anchor_id=anchor_id,
                principal_id=principal_id,
                at=at,
            )
        )


def scheduled_result_to_typed_fact(
    anchor: ScheduledConversationAnchor,
    *,
    token_estimator: Callable[[str], int],
) -> TranscriptEntry:
    """Project one scheduled result as provenance-labeled data, never an instruction."""
    text = scheduled_result_fact_text(anchor)
    return TranscriptEntry(
        entry_id=f"scheduled-result-{anchor.anchor_id}",
        role=EntryRole.SYSTEM,
        kind=EntryKind.TYPED_FACT,
        text=text,
        tokens=token_estimator(text),
        sequence=-1,
        trusted=False,
        metadata={
            "anchor_id": anchor.anchor_id,
            "run_id": anchor.run_id,
            "result_digest": anchor.result_digest,
            "instruction_authority": "none",
            "provenance": "scheduled-result",
        },
    )


def _identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "ContinuationAccess",
    "ContinuationAccessDeniedError",
    "ContinuationAnchorState",
    "ContinuationAudience",
    "ContinuationAuditEvent",
    "ContinuationAuditKind",
    "ContinuationAuditSink",
    "ContinuationMode",
    "InMemoryContinuationAuditSink",
    "InMemoryScheduledConversationAnchorStore",
    "ScheduledContinuationService",
    "ScheduledConversationAnchor",
    "ScheduledConversationAnchorStore",
    "ScheduledResultOrigin",
    "StateStoreContinuationAuditSink",
    "anchor_id_for_run",
    "scheduled_result_to_typed_fact",
]
