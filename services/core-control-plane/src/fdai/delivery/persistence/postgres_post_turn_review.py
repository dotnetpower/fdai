"""PostgreSQL status ledger for post-turn improvement reviews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.learning import (
    PostTurnProposalKind,
    PostTurnReviewRecord,
    PostTurnReviewState,
)

_COLUMNS: Final = (
    "review_id, principal_scope, state, reasons, proposal_kind, proposal_ref, "
    "dedup_key, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class PostgresPostTurnReviewLedgerConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresPostTurnReviewLedgerConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresPostTurnReviewLedgerConfig timeouts MUST be positive")


class PostgresPostTurnReviewLedger:
    """Atomic review idempotency and proposal reservation across replicas."""

    def __init__(self, *, config: PostgresPostTurnReviewLedgerConfig) -> None:
        self._config = config

    async def start(self, record: PostTurnReviewRecord) -> tuple[PostTurnReviewRecord, bool]:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO post_turn_review ({_COLUMNS})
                VALUES (%s, %s, %s, %s, NULL, NULL, NULL, %s, %s)
                ON CONFLICT (review_id) DO NOTHING
                RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    record.review_id,
                    record.principal_scope,
                    record.state.value,
                    list(record.reasons),
                    record.created_at,
                    record.updated_at,
                ),
            )
            row = await cursor.fetchone()
            created = row is not None
            if row is None:
                cursor = await connection.execute(
                    f"SELECT {_COLUMNS} FROM post_turn_review WHERE review_id = %s",  # noqa: S608
                    (record.review_id,),
                )
                row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("post-turn review insert returned no row")
        existing = _row_to_record(row)
        if existing.principal_scope != record.principal_scope:
            raise ValueError("post-turn review id was reused for another principal scope")
        return existing, created

    async def reserve_proposal(self, *, review_id: str, dedup_key: str) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO post_turn_proposal_claim (dedup_key, review_id)
                SELECT %s, review_id
                  FROM post_turn_review
                 WHERE review_id = %s AND state = 'pending'
                ON CONFLICT (dedup_key) DO NOTHING
                RETURNING dedup_key
                """,
                (dedup_key, review_id),
            )
            reserved = await cursor.fetchone() is not None
            if reserved:
                await connection.execute(
                    "UPDATE post_turn_review SET dedup_key = %s WHERE review_id = %s",
                    (dedup_key, review_id),
                )
        return reserved

    async def finish(
        self,
        review_id: str,
        *,
        state: PostTurnReviewState,
        reasons: tuple[str, ...],
        updated_at: Any,
        proposal_kind: PostTurnProposalKind | None = None,
        proposal_ref: str | None = None,
        dedup_key: str | None = None,
    ) -> PostTurnReviewRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE post_turn_review
                   SET state = %s, reasons = %s, proposal_kind = %s, proposal_ref = %s,
                       dedup_key = COALESCE(%s, dedup_key), updated_at = %s
                 WHERE review_id = %s AND state = 'pending'
                RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    state.value,
                    list(reasons),
                    proposal_kind.value if proposal_kind is not None else None,
                    proposal_ref,
                    dedup_key,
                    updated_at,
                    review_id,
                ),
            )
            row = await cursor.fetchone()
        return _row_to_record(row) if row is not None else await self.get(review_id)

    async def get(self, review_id: str) -> PostTurnReviewRecord:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM post_turn_review WHERE review_id = %s",  # noqa: S608
                (review_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"post-turn review {review_id!r} was not found")
        return _row_to_record(row)

    async def list(self) -> tuple[PostTurnReviewRecord, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM post_turn_review ORDER BY updated_at DESC, review_id",  # noqa: S608
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_record(row) for row in rows)

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


def _row_to_record(row: dict[str, Any]) -> PostTurnReviewRecord:
    proposal_kind = row["proposal_kind"]
    return PostTurnReviewRecord(
        review_id=str(row["review_id"]),
        principal_scope=str(row["principal_scope"]),
        state=PostTurnReviewState(str(row["state"])),
        reasons=tuple(str(item) for item in row["reasons"]),
        proposal_kind=(
            PostTurnProposalKind(str(proposal_kind)) if proposal_kind is not None else None
        ),
        proposal_ref=str(row["proposal_ref"]) if row["proposal_ref"] is not None else None,
        dedup_key=str(row["dedup_key"]) if row["dedup_key"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresPostTurnReviewLedger", "PostgresPostTurnReviewLedgerConfig"]
