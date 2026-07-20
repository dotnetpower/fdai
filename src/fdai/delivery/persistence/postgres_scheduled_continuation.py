"""PostgreSQL persistence for access-scoped scheduled continuation anchors."""

# ruff: noqa: S608 - SQL identifiers are module constants; runtime values are parametrized.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationAudience,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
)

_COLUMNS: Final = (
    "anchor_id, task_id, run_id, owner_principal_id, scope_ref, mode, origin, "
    "result_digest, result_summary, evidence_refs, observation_started_at, "
    "observation_ended_at, created_at, expires_at, state"
)


@dataclass(frozen=True, slots=True)
class PostgresScheduledContinuationStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresScheduledContinuationStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresScheduledContinuationStoreConfig timeouts MUST be positive")


class PostgresScheduledConversationAnchorStore:
    def __init__(self, *, config: PostgresScheduledContinuationStoreConfig) -> None:
        self._config: Final = config

    async def create(self, anchor: ScheduledConversationAnchor) -> ScheduledConversationAnchor:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO scheduled_conversation_anchor ({_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, "
                "%s, %s, %s, %s, %s) "
                "ON CONFLICT (run_id) DO NOTHING RETURNING anchor_id",  # noqa: S608
                _values(anchor),
            )
            if await cursor.fetchone() is not None:
                return anchor
            read = await connection.execute(
                f"SELECT {_COLUMNS} FROM scheduled_conversation_anchor WHERE run_id = %s",  # noqa: S608
                (anchor.run_id,),
            )
            row = await read.fetchone()
            if row is None or _row_to_anchor(row) != anchor:
                raise ValueError("scheduled run already has a different continuation anchor")
            return _row_to_anchor(row)

    async def get(self, anchor_id: str) -> ScheduledConversationAnchor | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM scheduled_conversation_anchor WHERE anchor_id = %s",  # noqa: S608
                (anchor_id,),
            )
            row = await cursor.fetchone()
        return _row_to_anchor(row) if row is not None else None

    async def expire(
        self, *, anchor_id: str, expected_state: ContinuationAnchorState
    ) -> ScheduledConversationAnchor | None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"UPDATE scheduled_conversation_anchor SET state = 'expired' "
                "WHERE anchor_id = %s AND state = %s "
                f"RETURNING {_COLUMNS}",  # noqa: S608
                (anchor_id, expected_state.value),
            )
            row = await cursor.fetchone()
            if row is not None:
                return _row_to_anchor(row)
            read = await connection.execute(
                f"SELECT {_COLUMNS} FROM scheduled_conversation_anchor WHERE anchor_id = %s",  # noqa: S608
                (anchor_id,),
            )
            current = await read.fetchone()
        return _row_to_anchor(current) if current is not None else None

    async def list_for_principal(
        self, *, principal_id: str, limit: int = 100
    ) -> tuple[ScheduledConversationAnchor, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM scheduled_conversation_anchor "
                "WHERE owner_principal_id = %s "
                "ORDER BY created_at DESC, anchor_id LIMIT %s",  # noqa: S608
                (principal_id, limit),
            )
            return tuple(_row_to_anchor(row) for row in await cursor.fetchall())

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


def _origin_json(origin: ScheduledResultOrigin) -> str:
    return json.dumps(
        {
            "audience": origin.audience.value,
            "channel_kind": origin.channel_kind,
            "channel_ref": origin.channel_ref,
            "conversation_ref": origin.conversation_ref,
            "thread_ref": origin.thread_ref,
        },
        sort_keys=True,
    )


def _origin(raw: Any) -> ScheduledResultOrigin:
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError("scheduled continuation origin MUST be a JSON object")
    return ScheduledResultOrigin(
        channel_kind=str(value["channel_kind"]),
        channel_ref=str(value["channel_ref"]),
        conversation_ref=str(value["conversation_ref"]),
        thread_ref=(str(value["thread_ref"]) if value.get("thread_ref") is not None else None),
        audience=ContinuationAudience(str(value["audience"])),
    )


def _values(anchor: ScheduledConversationAnchor) -> tuple[object, ...]:
    return (
        anchor.anchor_id,
        anchor.task_id,
        anchor.run_id,
        anchor.owner_principal_id,
        anchor.scope_ref,
        anchor.mode.value,
        _origin_json(anchor.origin),
        anchor.result_digest,
        anchor.result_summary,
        json.dumps(anchor.evidence_refs),
        anchor.observation_started_at,
        anchor.observation_ended_at,
        anchor.created_at,
        anchor.expires_at,
        anchor.state.value,
    )


def _row_to_anchor(row: dict[str, Any]) -> ScheduledConversationAnchor:
    evidence = (
        json.loads(row["evidence_refs"])
        if isinstance(row["evidence_refs"], str)
        else row["evidence_refs"]
    )
    return ScheduledConversationAnchor(
        anchor_id=str(row["anchor_id"]),
        task_id=str(row["task_id"]),
        run_id=str(row["run_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        scope_ref=str(row["scope_ref"]),
        mode=ContinuationMode(str(row["mode"])),
        origin=_origin(row["origin"]),
        result_digest=str(row["result_digest"]),
        result_summary=str(row["result_summary"]),
        evidence_refs=tuple(str(ref) for ref in evidence),
        observation_started_at=row["observation_started_at"],
        observation_ended_at=row["observation_ended_at"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        state=ContinuationAnchorState(str(row["state"])),
    )


__all__ = [
    "PostgresScheduledContinuationStoreConfig",
    "PostgresScheduledConversationAnchorStore",
]
