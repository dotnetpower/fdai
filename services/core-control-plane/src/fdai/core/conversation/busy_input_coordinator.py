"""Shared coordinator for durable queue, interrupt, and steer semantics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDecision,
    BusyInputDisposition,
    BusyInputMode,
    BusySessionState,
    PendingBusyInput,
)
from fdai.core.conversation.busy_input_store import BusyInputConflictError, BusyInputStore


class BusyInputMetrics(Protocol):
    def increment(self, name: str) -> None: ...


@dataclass(slots=True)
class ActiveConversationTurn:
    session_id: str
    turn_id: str
    principal_id: str
    cancel_event: asyncio.Event
    steer_event: asyncio.Event


class BusyInputCoordinator:
    def __init__(
        self,
        *,
        store: BusyInputStore,
        metrics: BusyInputMetrics | None = None,
    ) -> None:
        self._store = store
        self._metrics = metrics
        self._active: dict[str, ActiveConversationTurn] = {}
        self._lock = asyncio.Lock()

    async def begin_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        principal_id: str,
        mode: BusyInputMode | None = None,
    ) -> ActiveConversationTurn:
        async with self._lock:
            state, _ = await self._store.create(
                session_id=session_id,
                owner_principal_id=principal_id,
                mode=mode or BusyInputMode.QUEUE,
            )
            if state.active_turn_id is not None:
                raise RuntimeError("conversation session already has an active turn")
            effective_mode = mode or state.mode
            await self._store.set_active_turn(
                session_id,
                principal_id=principal_id,
                turn_id=turn_id,
                mode=effective_mode,
                expected_revision=state.revision,
            )
            active = ActiveConversationTurn(
                session_id=session_id,
                turn_id=turn_id,
                principal_id=principal_id,
                cancel_event=asyncio.Event(),
                steer_event=asyncio.Event(),
            )
            self._active[session_id] = active
            return active

    async def submit(
        self,
        incoming: BusyInput,
        *,
        now: datetime | None = None,
    ) -> BusyInputDecision:
        decision = await self._store.submit(incoming, now=now or datetime.now(UTC))
        active = self._active.get(incoming.session_id)
        if decision.record.disposition is BusyInputDisposition.INTERRUPTING:
            if active is not None:
                active.cancel_event.set()
            else:
                self._increment("race_recovery")
            self._increment("interrupting")
        elif decision.record.disposition is BusyInputDisposition.STEERED:
            if active is not None:
                active.steer_event.set()
            else:
                self._increment("race_recovery")
            self._increment("steered")
        elif decision.record.disposition is BusyInputDisposition.QUEUED:
            self._increment("queued")
        else:
            self._increment("rejected")
        if decision.duplicate:
            self._increment("duplicate")
        if decision.reason == "queue_capacity_exceeded":
            self._increment("overflow")
        elif decision.reason == "input_expired":
            self._increment("expiry")
        return decision

    async def safe_boundary(
        self,
        *,
        session_id: str,
        principal_id: str,
        at: datetime | None = None,
    ) -> PendingBusyInput | None:
        active = self._active.get(session_id)
        if active is None or not active.steer_event.is_set():
            return None
        pending = await self._store.list_pending(
            session_id,
            principal_id=principal_id,
            limit=32,
        )
        selected = next(
            (item for item in pending if item.disposition is BusyInputDisposition.STEERED),
            None,
        )
        if selected is None:
            active.steer_event.clear()
            return None
        try:
            _, consumed = await self._store.consume(
                session_id,
                sequence=selected.sequence,
                principal_id=principal_id,
                at=at or datetime.now(UTC),
            )
        except (BusyInputConflictError, LookupError, ValueError):
            self._increment("race_recovery")
            active.steer_event.clear()
            return None
        remaining = await self._store.list_pending(
            session_id,
            principal_id=principal_id,
            limit=32,
        )
        if not any(item.disposition is BusyInputDisposition.STEERED for item in remaining):
            active.steer_event.clear()
        return consumed

    async def finish_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        principal_id: str,
    ) -> None:
        steer_fallbacks = 0
        try:
            pending = await self._store.list_pending(
                session_id,
                principal_id=principal_id,
                limit=32,
            )
            steer_fallbacks = sum(
                item.disposition is BusyInputDisposition.STEERED for item in pending
            )
            await self._store.finish_turn(
                session_id,
                principal_id=principal_id,
                turn_id=turn_id,
            )
            for _ in range(steer_fallbacks):
                self._increment("steer_fallback")
        finally:
            async with self._lock:
                active = self._active.get(session_id)
                if active is not None and active.turn_id == turn_id:
                    self._active.pop(session_id, None)

    async def pending(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> tuple[PendingBusyInput, ...]:
        return await self._store.list_pending(
            session_id,
            principal_id=principal_id,
            limit=32,
        )

    async def status(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> BusySessionState | None:
        return await self._store.get(session_id, principal_id=principal_id)

    async def set_mode(
        self,
        *,
        session_id: str,
        principal_id: str,
        mode: BusyInputMode,
    ) -> BusySessionState:
        state, created = await self._store.create(
            session_id=session_id,
            owner_principal_id=principal_id,
            mode=mode,
        )
        if created:
            return state
        return await self._store.set_mode(
            session_id,
            principal_id=principal_id,
            mode=mode,
        )

    async def cancel_current(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> bool:
        state = await self._store.get(session_id, principal_id=principal_id)
        if state is None or state.active_turn_id is None:
            return False
        active = self._active.get(session_id)
        if active is None or active.principal_id != principal_id:
            self._increment("race_recovery")
            return False
        active.cancel_event.set()
        return True

    async def expire_pending(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[PendingBusyInput, ...]:
        expired = await self._store.expire_pending(now=now, limit=limit)
        for _ in expired:
            self._increment("expiry")
        return expired

    def active(self, session_id: str) -> ActiveConversationTurn | None:
        return self._active.get(session_id)

    def _increment(self, name: str) -> None:
        if self._metrics is not None:
            self._metrics.increment(name)


__all__ = [
    "ActiveConversationTurn",
    "BusyInputCoordinator",
    "BusyInputMetrics",
]
