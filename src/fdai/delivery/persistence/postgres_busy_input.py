"""Transactional PostgreSQL store for busy-session input arbitration."""

# ruff: noqa: S608 - interpolated column lists are module constants; values are bound.

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, cast

import psycopg
from psycopg.rows import dict_row

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDecision,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
    BusyPendingStatus,
    BusySessionState,
    PendingBusyInput,
    arbitrate_busy_input,
    consume_pending_input,
    finish_active_turn,
)
from fdai.core.conversation.busy_input_store import BusyInputConflictError

_MAX_BIGINT: Final = 9_223_372_036_854_775_807
_STATE_COLUMNS: Final = (
    "session_id, owner_principal_id, mode, active_turn_id, revision, next_sequence"
)
_INPUT_COLUMNS: Final = (
    "session_id, input_id, idempotency_key, principal_id, content, kind, "
    "received_at, expires_at, sequence, disposition, status, consumed_at"
)


@dataclass(frozen=True, slots=True)
class PostgresBusyInputStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresBusyInputStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresBusyInputStoreConfig timeouts MUST be positive")


class PostgresBusyInputStore:
    def __init__(self, *, config: PostgresBusyInputStoreConfig) -> None:
        self._config = config

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
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO busy_session_state ("
                f"{_STATE_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (session_id) DO NOTHING "
                f"RETURNING {_STATE_COLUMNS}",
                (session_id, owner_principal_id, mode.value, None, 1, 0),
            )
            row = await cursor.fetchone()
            if row is not None:
                return candidate, True
            current = await self._required_state(connection, session_id, for_update=True)
            if current.owner_principal_id != owner_principal_id:
                raise BusyInputConflictError("busy session is owned by another principal")
            return await self._project(connection, current), False

    async def get(
        self,
        session_id: str,
        *,
        principal_id: str,
    ) -> BusySessionState | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_STATE_COLUMNS} FROM busy_session_state "
                "WHERE session_id = %s AND owner_principal_id = %s",
                (session_id, principal_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return await self._project(connection, _state(row))

    async def set_active_turn(
        self,
        session_id: str,
        *,
        principal_id: str,
        turn_id: str,
        mode: BusyInputMode,
        expected_revision: int,
    ) -> BusySessionState:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._authorized_state(connection, session_id, principal_id)
            self._expect_revision(current, expected_revision)
            updated = replace(
                current,
                active_turn_id=turn_id,
                mode=mode,
                revision=self._next_revision(current),
            )
            row = await self._update_state(connection, updated, expected_revision=current.revision)
            return await self._project(connection, _state(row))

    async def set_mode(
        self,
        session_id: str,
        *,
        principal_id: str,
        mode: BusyInputMode,
    ) -> BusySessionState:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._authorized_state(connection, session_id, principal_id)
            updated = replace(
                current,
                mode=mode,
                revision=self._next_revision(current),
            )
            row = await self._update_state(
                connection,
                updated,
                expected_revision=current.revision,
            )
            return await self._project(connection, _state(row))

    async def submit(self, incoming: BusyInput, *, now: datetime) -> BusyInputDecision:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._required_state(
                connection,
                incoming.session_id,
                for_update=True,
            )
            existing = await self._existing_input(connection, incoming)
            if existing is not None:
                if (
                    existing.input.idempotency_key != incoming.idempotency_key
                    or existing.input != incoming
                ):
                    raise BusyInputConflictError(
                        "busy input id or idempotency key was reused with another input"
                    )
                return BusyInputDecision(
                    state=await self._project(connection, current),
                    record=existing,
                    duplicate=True,
                )
            projected = await self._project(connection, current)
            decision = arbitrate_busy_input(projected, incoming, now=now)
            await self._insert_input(connection, decision.record)
            if decision.state.revision != current.revision:
                self._next_revision(current)
                await self._update_state(
                    connection,
                    replace(decision.state, pending=()),
                    expected_revision=current.revision,
                )
            return decision

    async def finish_turn(
        self,
        session_id: str,
        *,
        principal_id: str,
        turn_id: str,
    ) -> BusySessionState:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._authorized_state(connection, session_id, principal_id)
            projected = await self._project(connection, current)
            updated = finish_active_turn(projected, turn_id=turn_id)
            self._next_revision(current)
            await connection.execute(
                "UPDATE busy_pending_input SET disposition = %s "
                "WHERE session_id = %s AND status = %s AND disposition = %s",
                (
                    BusyInputDisposition.QUEUED.value,
                    session_id,
                    BusyPendingStatus.PENDING.value,
                    BusyInputDisposition.STEERED.value,
                ),
            )
            row = await self._update_state(
                connection,
                replace(updated, pending=()),
                expected_revision=current.revision,
            )
            return await self._project(connection, _state(row))

    async def consume(
        self,
        session_id: str,
        *,
        sequence: int,
        principal_id: str,
        at: datetime,
    ) -> tuple[BusySessionState, PendingBusyInput]:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            current = await self._required_state(connection, session_id, for_update=True)
            projected = await self._project(connection, current)
            updated, consumed = consume_pending_input(
                projected,
                sequence=sequence,
                principal_id=principal_id,
                at=at,
            )
            self._next_revision(current)
            cursor = await connection.execute(
                "UPDATE busy_pending_input SET status = %s, consumed_at = %s "
                "WHERE session_id = %s AND sequence = %s AND status = %s "
                f"RETURNING {_INPUT_COLUMNS}",
                (
                    BusyPendingStatus.CONSUMED.value,
                    at,
                    session_id,
                    sequence,
                    BusyPendingStatus.PENDING.value,
                ),
            )
            if await cursor.fetchone() is None:  # pragma: no cover - state lock preserves row
                raise BusyInputConflictError("busy input consumption conflict")
            row = await self._update_state(
                connection,
                replace(updated, pending=()),
                expected_revision=current.revision,
            )
            return await self._project(connection, _state(row)), consumed

    async def list_pending(
        self,
        session_id: str,
        *,
        principal_id: str,
        limit: int = 32,
    ) -> tuple[PendingBusyInput, ...]:
        _limit(limit, 32)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT 1 FROM busy_session_state "
                "WHERE session_id = %s AND owner_principal_id = %s",
                (session_id, principal_id),
            )
            if await cursor.fetchone() is None:
                raise PermissionError("busy session principal mismatch")
            rows = await connection.execute(
                f"SELECT {_INPUT_COLUMNS} FROM busy_pending_input "
                "WHERE session_id = %s AND status = %s "
                "ORDER BY sequence LIMIT %s",
                (session_id, BusyPendingStatus.PENDING.value, limit),
            )
            return tuple(_record(row) for row in await rows.fetchall())

    async def expire_pending(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[PendingBusyInput, ...]:
        _aware(now)
        _limit(limit, 1_000)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            sessions = await connection.execute(
                "SELECT DISTINCT session_id FROM ("
                "SELECT session_id, expires_at, sequence FROM busy_pending_input "
                "WHERE status = %s AND expires_at <= %s "
                "ORDER BY expires_at, session_id, sequence LIMIT %s"
                ") AS candidate ORDER BY session_id",
                (BusyPendingStatus.PENDING.value, now, limit),
            )
            session_ids = [str(row["session_id"]) for row in await sessions.fetchall()]
            if not session_ids:
                return ()
            locked = await connection.execute(
                f"SELECT {_STATE_COLUMNS} FROM busy_session_state "
                "WHERE session_id = ANY(%s) ORDER BY session_id FOR UPDATE",
                (session_ids,),
            )
            locked_states = [_state(row) for row in await locked.fetchall()]
            for state in locked_states:
                self._next_revision(state)
            candidates = await connection.execute(
                f"SELECT {_INPUT_COLUMNS} FROM busy_pending_input "
                "WHERE session_id = ANY(%s) AND status = %s AND expires_at <= %s "
                "ORDER BY expires_at, session_id, sequence FOR UPDATE LIMIT %s",
                (session_ids, BusyPendingStatus.PENDING.value, now, limit),
            )
            records = [_record(row) for row in await candidates.fetchall()]
            changed_sessions = sorted({record.input.session_id for record in records})
            for record in records:
                await connection.execute(
                    "UPDATE busy_pending_input SET status = %s "
                    "WHERE session_id = %s AND input_id = %s AND status = %s",
                    (
                        BusyPendingStatus.EXPIRED.value,
                        record.input.session_id,
                        record.input.input_id,
                        BusyPendingStatus.PENDING.value,
                    ),
                )
            if changed_sessions:
                await connection.execute(
                    "UPDATE busy_session_state SET revision = revision + 1 "
                    "WHERE session_id = ANY(%s)",
                    (changed_sessions,),
                )
            return tuple(replace(record, status=BusyPendingStatus.EXPIRED) for record in records)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{self._config.statement_timeout_ms}ms",),
        )

    async def _required_state(
        self,
        connection: psycopg.AsyncConnection[Any],
        session_id: str,
        *,
        for_update: bool,
    ) -> BusySessionState:
        suffix = " FOR UPDATE" if for_update else ""
        cursor = await connection.execute(
            f"SELECT {_STATE_COLUMNS} FROM busy_session_state WHERE session_id = %s{suffix}",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"busy session {session_id!r} was not found")
        return _state(row)

    async def _authorized_state(
        self,
        connection: psycopg.AsyncConnection[Any],
        session_id: str,
        principal_id: str,
    ) -> BusySessionState:
        current = await self._required_state(connection, session_id, for_update=True)
        if current.owner_principal_id != principal_id:
            raise PermissionError("busy session principal mismatch")
        return current

    async def _project(
        self,
        connection: psycopg.AsyncConnection[Any],
        state: BusySessionState,
    ) -> BusySessionState:
        cursor = await connection.execute(
            f"SELECT {_INPUT_COLUMNS} FROM busy_pending_input "
            "WHERE session_id = %s AND status = %s ORDER BY sequence",
            (state.session_id, BusyPendingStatus.PENDING.value),
        )
        return replace(state, pending=tuple(_record(row) for row in await cursor.fetchall()))

    async def _existing_input(
        self,
        connection: psycopg.AsyncConnection[Any],
        incoming: BusyInput,
    ) -> PendingBusyInput | None:
        cursor = await connection.execute(
            f"SELECT {_INPUT_COLUMNS} FROM busy_pending_input "
            "WHERE session_id = %s AND (input_id = %s OR idempotency_key = %s)",
            (incoming.session_id, incoming.input_id, incoming.idempotency_key),
        )
        row = await cursor.fetchone()
        return _record(row) if row is not None else None

    async def _insert_input(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: PendingBusyInput,
    ) -> None:
        incoming = record.input
        await connection.execute(
            "INSERT INTO busy_pending_input ("
            f"{_INPUT_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                incoming.session_id,
                incoming.input_id,
                incoming.idempotency_key,
                incoming.principal_id,
                incoming.content,
                incoming.kind.value,
                incoming.received_at,
                incoming.expires_at,
                record.sequence,
                record.disposition.value,
                record.status.value,
                record.consumed_at,
            ),
        )

    async def _update_state(
        self,
        connection: psycopg.AsyncConnection[Any],
        state: BusySessionState,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        cursor = await connection.execute(
            "UPDATE busy_session_state SET mode = %s, active_turn_id = %s, "
            "revision = %s, next_sequence = %s "
            "WHERE session_id = %s AND revision = %s "
            f"RETURNING {_STATE_COLUMNS}",
            (
                state.mode.value,
                state.active_turn_id,
                state.revision,
                state.next_sequence,
                state.session_id,
                expected_revision,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise BusyInputConflictError("busy session revision conflict")
        return cast(dict[str, Any], row)

    @staticmethod
    def _expect_revision(state: BusySessionState, expected_revision: int) -> None:
        if state.revision != expected_revision:
            raise BusyInputConflictError(
                f"busy session revision mismatch: expected {expected_revision}, "
                f"current {state.revision}"
            )

    @staticmethod
    def _next_revision(state: BusySessionState) -> int:
        if state.revision >= _MAX_BIGINT:
            raise BusyInputConflictError("busy session revision is exhausted")
        return state.revision + 1


def _state(row: dict[str, Any]) -> BusySessionState:
    active_turn = row["active_turn_id"]
    return BusySessionState(
        session_id=str(row["session_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        mode=BusyInputMode(str(row["mode"])),
        active_turn_id=str(active_turn) if active_turn is not None else None,
        revision=int(row["revision"]),
        next_sequence=int(row["next_sequence"]),
    )


def _record(row: dict[str, Any]) -> PendingBusyInput:
    consumed_at = row["consumed_at"]
    incoming = BusyInput(
        input_id=str(row["input_id"]),
        idempotency_key=str(row["idempotency_key"]),
        session_id=str(row["session_id"]),
        principal_id=str(row["principal_id"]),
        content=str(row["content"]),
        kind=BusyInputKind(str(row["kind"])),
        received_at=cast(datetime, row["received_at"]),
        expires_at=cast(datetime, row["expires_at"]),
    )
    return PendingBusyInput(
        input=incoming,
        sequence=int(row["sequence"]),
        disposition=BusyInputDisposition(str(row["disposition"])),
        status=BusyPendingStatus(str(row["status"])),
        consumed_at=cast(datetime, consumed_at) if consumed_at is not None else None,
    )


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


def _aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("now MUST be timezone-aware")


__all__ = [
    "PostgresBusyInputStore",
    "PostgresBusyInputStoreConfig",
]
