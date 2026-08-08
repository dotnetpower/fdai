"""Durable busy-input seam and deterministic in-memory reference store."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDecision,
    BusyInputMode,
    BusyPendingStatus,
    BusySessionState,
    PendingBusyInput,
    arbitrate_busy_input,
    consume_pending_input,
    finish_active_turn,
)


class BusyInputConflictError(RuntimeError):
    """A busy-session write lost its expected-state race."""


class BusyInputStore(Protocol):
    async def create(
        self,
        *,
        session_id: str,
        owner_principal_id: str,
        mode: BusyInputMode = BusyInputMode.QUEUE,
    ) -> tuple[BusySessionState, bool]: ...

    async def get(
        self,
        session_id: str,
        *,
        principal_id: str,
    ) -> BusySessionState | None: ...

    async def set_active_turn(
        self,
        session_id: str,
        *,
        principal_id: str,
        turn_id: str,
        mode: BusyInputMode,
        expected_revision: int,
    ) -> BusySessionState: ...

    async def set_mode(
        self,
        session_id: str,
        *,
        principal_id: str,
        mode: BusyInputMode,
    ) -> BusySessionState: ...

    async def submit(self, incoming: BusyInput, *, now: datetime) -> BusyInputDecision: ...

    async def finish_turn(
        self,
        session_id: str,
        *,
        principal_id: str,
        turn_id: str,
    ) -> BusySessionState: ...

    async def consume(
        self,
        session_id: str,
        *,
        sequence: int,
        principal_id: str,
        at: datetime,
    ) -> tuple[BusySessionState, PendingBusyInput]: ...

    async def list_pending(
        self,
        session_id: str,
        *,
        principal_id: str,
        limit: int = 32,
    ) -> tuple[PendingBusyInput, ...]: ...

    async def expire_pending(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[PendingBusyInput, ...]: ...


class InMemoryBusyInputStore:
    """Serialize the protocol while retaining terminal disposition history."""

    def __init__(self) -> None:
        self._states: dict[str, BusySessionState] = {}
        self._records: dict[str, list[PendingBusyInput]] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        session_id: str,
        owner_principal_id: str,
        mode: BusyInputMode = BusyInputMode.QUEUE,
    ) -> tuple[BusySessionState, bool]:
        candidate = BusySessionState(
            session_id=session_id,
            owner_principal_id=owner_principal_id,
            mode=mode,
            revision=1,
            next_sequence=0,
        )
        async with self._lock:
            current = self._states.get(session_id)
            if current is not None:
                if current.owner_principal_id != owner_principal_id:
                    raise BusyInputConflictError("busy session is owned by another principal")
                return self._project(current), False
            self._states[session_id] = candidate
            self._records[session_id] = []
            return candidate, True

    async def get(
        self,
        session_id: str,
        *,
        principal_id: str,
    ) -> BusySessionState | None:
        async with self._lock:
            current = self._states.get(session_id)
            if current is None or current.owner_principal_id != principal_id:
                return None
            return self._project(current)

    async def set_active_turn(
        self,
        session_id: str,
        *,
        principal_id: str,
        turn_id: str,
        mode: BusyInputMode,
        expected_revision: int,
    ) -> BusySessionState:
        async with self._lock:
            current = self._authorized(session_id, principal_id)
            self._expect_revision(current, expected_revision)
            updated = replace(
                current,
                active_turn_id=turn_id,
                mode=mode,
                revision=current.revision + 1,
            )
            self._states[session_id] = updated
            return self._project(updated)

    async def set_mode(
        self,
        session_id: str,
        *,
        principal_id: str,
        mode: BusyInputMode,
    ) -> BusySessionState:
        async with self._lock:
            current = self._authorized(session_id, principal_id)
            updated = replace(current, mode=mode, revision=current.revision + 1)
            self._states[session_id] = updated
            return self._project(updated)

    async def submit(self, incoming: BusyInput, *, now: datetime) -> BusyInputDecision:
        async with self._lock:
            current = self._required(incoming.session_id)
            duplicate = self._duplicate(incoming)
            if duplicate is not None:
                return BusyInputDecision(
                    state=self._project(current),
                    record=duplicate,
                    duplicate=True,
                )
            decision = arbitrate_busy_input(self._project(current), incoming, now=now)
            self._records[incoming.session_id].append(decision.record)
            if decision.state.revision != current.revision:
                self._states[incoming.session_id] = replace(decision.state, pending=())
            return replace(decision, state=self._project(self._states[incoming.session_id]))

    async def finish_turn(
        self,
        session_id: str,
        *,
        principal_id: str,
        turn_id: str,
    ) -> BusySessionState:
        async with self._lock:
            current = self._authorized(session_id, principal_id)
            updated = finish_active_turn(self._project(current), turn_id=turn_id)
            self._replace_pending(session_id, updated.pending)
            self._states[session_id] = replace(updated, pending=())
            return self._project(self._states[session_id])

    async def consume(
        self,
        session_id: str,
        *,
        sequence: int,
        principal_id: str,
        at: datetime,
    ) -> tuple[BusySessionState, PendingBusyInput]:
        async with self._lock:
            current = self._required(session_id)
            updated, consumed = consume_pending_input(
                self._project(current),
                sequence=sequence,
                principal_id=principal_id,
                at=at,
            )
            self._replace_pending(session_id, updated.pending)
            self._states[session_id] = replace(updated, pending=())
            return self._project(self._states[session_id]), consumed

    async def list_pending(
        self,
        session_id: str,
        *,
        principal_id: str,
        limit: int = 32,
    ) -> tuple[PendingBusyInput, ...]:
        _limit(limit, 32)
        async with self._lock:
            self._authorized(session_id, principal_id)
            pending = self._pending(session_id)
            return tuple(pending[:limit])

    async def expire_pending(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[PendingBusyInput, ...]:
        _aware(now)
        _limit(limit, 1_000)
        async with self._lock:
            candidates = sorted(
                (
                    (session_id, item)
                    for session_id, records in self._records.items()
                    for item in records
                    if item.status is BusyPendingStatus.PENDING and item.input.expires_at <= now
                ),
                key=lambda pair: (pair[1].input.expires_at, pair[0], pair[1].sequence),
            )[:limit]
            expired: list[PendingBusyInput] = []
            changed_sessions: set[str] = set()
            for session_id, item in candidates:
                replacement = replace(item, status=BusyPendingStatus.EXPIRED)
                self._replace_record(session_id, replacement)
                expired.append(replacement)
                changed_sessions.add(session_id)
            for session_id in changed_sessions:
                current = self._states[session_id]
                self._states[session_id] = replace(current, revision=current.revision + 1)
            return tuple(expired)

    def _project(self, state: BusySessionState) -> BusySessionState:
        return replace(state, pending=tuple(self._pending(state.session_id)))

    def _pending(self, session_id: str) -> list[PendingBusyInput]:
        return [
            item for item in self._records[session_id] if item.status is BusyPendingStatus.PENDING
        ]

    def _duplicate(self, incoming: BusyInput) -> PendingBusyInput | None:
        for item in self._records[incoming.session_id]:
            if item.input.idempotency_key != incoming.idempotency_key:
                continue
            if item.input != incoming:
                raise BusyInputConflictError(
                    "busy input idempotency key was reused with another input"
                )
            return item
        return None

    def _replace_pending(
        self,
        session_id: str,
        pending: tuple[PendingBusyInput, ...],
    ) -> None:
        for item in pending:
            self._replace_record(session_id, item)

    def _replace_record(self, session_id: str, replacement: PendingBusyInput) -> None:
        records = self._records[session_id]
        for index, item in enumerate(records):
            if item.input.input_id == replacement.input.input_id:
                records[index] = replacement
                return
        raise LookupError(f"busy input {replacement.input.input_id!r} was not found")

    def _required(self, session_id: str) -> BusySessionState:
        try:
            return self._states[session_id]
        except KeyError as exc:
            raise LookupError(f"busy session {session_id!r} was not found") from exc

    def _authorized(self, session_id: str, principal_id: str) -> BusySessionState:
        current = self._required(session_id)
        if current.owner_principal_id != principal_id:
            raise PermissionError("busy session principal mismatch")
        return current

    @staticmethod
    def _expect_revision(state: BusySessionState, expected_revision: int) -> None:
        if state.revision != expected_revision:
            raise BusyInputConflictError(
                f"busy session revision mismatch: expected {expected_revision}, "
                f"current {state.revision}"
            )


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


def _aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("now MUST be timezone-aware")


__all__ = [
    "BusyInputConflictError",
    "BusyInputStore",
    "InMemoryBusyInputStore",
]
