"""Atomic PostgreSQL operator-memory compaction and rollback repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.core.operator_memory import (
    MemoryCompactionCandidate,
    MemoryCompactionError,
    MemoryCompactionState,
    OperatorMemoryEntry,
)

_COLUMNS: Final = (
    "candidate_id, scope_kind, scope_ref, category, body, source_entry_ids, source_refs, "
    "proposed_by_agent, created_at, state, reviewed_by, review_reason, reviewed_at, "
    "promoted_entry_id"
)


@dataclass(frozen=True, slots=True)
class PostgresMemoryCompactionRepositoryConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresMemoryCompactionRepositoryConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresMemoryCompactionRepositoryConfig timeouts MUST be positive")


class PostgresMemoryCompactionRepository:
    """Persist candidates and atomically apply or roll back supersession pointers."""

    def __init__(self, *, config: PostgresMemoryCompactionRepositoryConfig) -> None:
        self._config = config

    async def create(self, candidate: MemoryCompactionCandidate) -> MemoryCompactionCandidate:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO memory_compaction_candidate ({_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s,
                        NULL, NULL, NULL, NULL)
                ON CONFLICT (candidate_id) DO NOTHING
                RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    candidate.candidate_id,
                    candidate.scope_kind,
                    candidate.scope_ref,
                    candidate.category,
                    candidate.body,
                    [str(value) for value in candidate.source_entry_ids],
                    list(candidate.source_refs),
                    candidate.proposed_by_agent,
                    candidate.created_at,
                    candidate.state.value,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                row = await self._select(connection, candidate.candidate_id)
        if row is None:
            raise RuntimeError("memory compaction insert returned no row")
        return _row_to_candidate(row)

    async def get(self, candidate_id: str) -> MemoryCompactionCandidate:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            row = await self._select(connection, candidate_id)
        if row is None:
            raise MemoryCompactionError("memory compaction candidate was not found")
        return _row_to_candidate(row)

    async def list(self, *, limit: int) -> tuple[MemoryCompactionCandidate, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("memory compaction review limit MUST be in [1, 200]")
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM memory_compaction_candidate "  # noqa: S608
                "ORDER BY created_at DESC, candidate_id DESC LIMIT %s",
                (limit,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_candidate(row) for row in rows)

    async def transition(
        self,
        candidate: MemoryCompactionCandidate,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE memory_compaction_candidate
                   SET state = %s, reviewed_by = %s, review_reason = %s,
                       reviewed_at = %s, updated_at = now()
                 WHERE candidate_id = %s AND state = %s
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    candidate.state.value,
                    candidate.reviewed_by,
                    candidate.review_reason,
                    candidate.reviewed_at,
                    candidate.candidate_id,
                    expected_state.value,
                ),
            )
            row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def promote(
        self,
        candidate: MemoryCompactionCandidate,
        entry: OperatorMemoryEntry,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            locked = await self._select(connection, candidate.candidate_id, for_update=True)
            if locked is None or str(locked["state"]) != expected_state.value:
                return None
            source_cursor = await connection.execute(
                """
                SELECT id FROM operator_memory
                 WHERE id = ANY(%s::uuid[]) AND superseded_by IS NULL
                   AND scope_kind = %s AND scope_ref = %s AND category = %s
                 FOR UPDATE
                """,
                (
                    [str(value) for value in candidate.source_entry_ids],
                    candidate.scope_kind,
                    candidate.scope_ref,
                    candidate.category,
                ),
            )
            source_rows = await source_cursor.fetchall()
            if len(source_rows) != len(candidate.source_entry_ids):
                raise MemoryCompactionError("memory compaction sources changed before promotion")
            await connection.execute(
                """
                INSERT INTO operator_memory (
                    id, scope_kind, scope_ref, category, body, source_event, source_ref,
                    author, approved_by, created_at, superseded_by, ttl_seconds
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
                """,
                (
                    str(entry.id),
                    entry.scope_kind.value,
                    entry.scope_ref,
                    entry.category.value,
                    entry.body,
                    entry.source_event.value,
                    entry.source_ref,
                    entry.author,
                    entry.approved_by,
                    entry.created_at,
                ),
            )
            await connection.execute(
                "UPDATE operator_memory SET superseded_by = %s "
                "WHERE id = ANY(%s::uuid[]) AND superseded_by IS NULL",
                (str(entry.id), [str(value) for value in candidate.source_entry_ids]),
            )
            cursor = await connection.execute(
                f"""
                UPDATE memory_compaction_candidate
                   SET state = 'promoted', promoted_entry_id = %s, updated_at = now()
                 WHERE candidate_id = %s AND state = %s
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (str(entry.id), candidate.candidate_id, expected_state.value),
            )
            row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def rollback(
        self,
        candidate: MemoryCompactionCandidate,
        *,
        expected_state: MemoryCompactionState,
    ) -> MemoryCompactionCandidate | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            locked = await self._select(connection, candidate.candidate_id, for_update=True)
            if (
                locked is None
                or str(locked["state"]) != expected_state.value
                or locked["promoted_entry_id"] is None
            ):
                return None
            promoted_id = UUID(str(locked["promoted_entry_id"]))
            source_ids = tuple(UUID(str(value)) for value in locked["source_entry_ids"])
            await connection.execute(
                "UPDATE operator_memory SET superseded_by = NULL "
                "WHERE id = ANY(%s::uuid[]) AND superseded_by = %s",
                ([str(value) for value in source_ids], str(promoted_id)),
            )
            await connection.execute(
                "UPDATE operator_memory SET superseded_by = %s WHERE id = %s",
                (str(source_ids[0]), str(promoted_id)),
            )
            cursor = await connection.execute(
                f"""
                UPDATE memory_compaction_candidate
                   SET state = 'rolled_back', updated_at = now()
                 WHERE candidate_id = %s AND state = %s
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (candidate.candidate_id, expected_state.value),
            )
            row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def _select(
        self,
        connection: psycopg.AsyncConnection[Any],
        candidate_id: str,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update else ""
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM memory_compaction_candidate "  # noqa: S608
            f"WHERE candidate_id = %s{suffix}",
            (candidate_id,),
        )
        return await cursor.fetchone()

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _row_to_candidate(row: dict[str, Any]) -> MemoryCompactionCandidate:
    return MemoryCompactionCandidate(
        candidate_id=str(row["candidate_id"]),
        scope_kind=str(row["scope_kind"]),
        scope_ref=str(row["scope_ref"]),
        category=str(row["category"]),
        body=str(row["body"]),
        source_entry_ids=tuple(UUID(str(value)) for value in row["source_entry_ids"]),
        source_refs=tuple(str(value) for value in row["source_refs"]),
        proposed_by_agent=str(row["proposed_by_agent"]),
        created_at=row["created_at"],
        state=MemoryCompactionState(str(row["state"])),
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        review_reason=str(row["review_reason"]) if row["review_reason"] is not None else None,
        reviewed_at=row["reviewed_at"],
        promoted_entry_id=(
            UUID(str(row["promoted_entry_id"])) if row["promoted_entry_id"] is not None else None
        ),
    )


__all__ = [
    "PostgresMemoryCompactionRepository",
    "PostgresMemoryCompactionRepositoryConfig",
]
