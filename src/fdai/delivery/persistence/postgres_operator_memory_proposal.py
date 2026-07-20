"""PostgreSQL persistence for reviewed operator-memory proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.core.operator_memory import (
    MemoryCategory,
    OperatorMemoryProposal,
    OperatorMemoryProposalError,
    OperatorMemoryProposalState,
    ScopeKind,
)

_COLUMNS: Final = (
    "proposal_id, content_hash, scope_kind, scope_ref, category, body, evidence_refs, "
    "proposed_by_agent, created_at, state, reviewed_by, review_reason, reviewed_at, "
    "materialized_entry_id"
)


@dataclass(frozen=True, slots=True)
class PostgresOperatorMemoryProposalStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresOperatorMemoryProposalStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresOperatorMemoryProposalStoreConfig timeouts MUST be positive")


class PostgresOperatorMemoryProposalStore:
    """Durable drafts with atomic expected-state transitions."""

    def __init__(self, *, config: PostgresOperatorMemoryProposalStoreConfig) -> None:
        self._config = config

    async def create(self, proposal: OperatorMemoryProposal) -> OperatorMemoryProposal:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO operator_memory_proposal ({_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL)
                ON CONFLICT (proposal_id) DO NOTHING
                RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    proposal.proposal_id,
                    proposal.content_hash,
                    proposal.scope_kind.value,
                    proposal.scope_ref,
                    proposal.category.value,
                    proposal.body,
                    list(proposal.evidence_refs),
                    proposal.proposed_by_agent,
                    proposal.created_at,
                    proposal.state.value,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                cursor = await connection.execute(
                    f"SELECT {_COLUMNS} FROM operator_memory_proposal WHERE proposal_id = %s",  # noqa: S608
                    (proposal.proposal_id,),
                )
                row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("operator-memory proposal insert returned no row")
        existing = _row_to_proposal(row)
        if existing.content_hash != proposal.content_hash:
            raise OperatorMemoryProposalError("operator-memory proposal id collision")
        return existing

    async def get(self, proposal_id: str) -> OperatorMemoryProposal:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM operator_memory_proposal WHERE proposal_id = %s",  # noqa: S608
                (proposal_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise OperatorMemoryProposalError(
                f"operator-memory proposal {proposal_id!r} was not found"
            )
        return _row_to_proposal(row)

    async def transition(
        self,
        proposal: OperatorMemoryProposal,
        *,
        expected_state: OperatorMemoryProposalState,
    ) -> OperatorMemoryProposal | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE operator_memory_proposal
                   SET state = %s, reviewed_by = %s, review_reason = %s, reviewed_at = %s,
                       materialized_entry_id = %s, updated_at = now()
                 WHERE proposal_id = %s AND state = %s
                RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    proposal.state.value,
                    proposal.reviewed_by,
                    proposal.review_reason,
                    proposal.reviewed_at,
                    str(proposal.materialized_entry_id)
                    if proposal.materialized_entry_id is not None
                    else None,
                    proposal.proposal_id,
                    expected_state.value,
                ),
            )
            row = await cursor.fetchone()
        return _row_to_proposal(row) if row is not None else None

    async def list(self) -> tuple[OperatorMemoryProposal, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM operator_memory_proposal ORDER BY proposal_id"  # noqa: S608
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_proposal(row) for row in rows)

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


def _row_to_proposal(row: dict[str, Any]) -> OperatorMemoryProposal:
    materialized = row["materialized_entry_id"]
    return OperatorMemoryProposal(
        proposal_id=str(row["proposal_id"]),
        content_hash=str(row["content_hash"]),
        scope_kind=ScopeKind(str(row["scope_kind"])),
        scope_ref=str(row["scope_ref"]),
        category=MemoryCategory(str(row["category"])),
        body=str(row["body"]),
        evidence_refs=tuple(str(item) for item in row["evidence_refs"]),
        proposed_by_agent=str(row["proposed_by_agent"]),
        created_at=row["created_at"],
        state=OperatorMemoryProposalState(str(row["state"])),
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        review_reason=(str(row["review_reason"]) if row["review_reason"] is not None else None),
        reviewed_at=row["reviewed_at"],
        materialized_entry_id=UUID(str(materialized)) if materialized is not None else None,
    )


__all__ = [
    "PostgresOperatorMemoryProposalStore",
    "PostgresOperatorMemoryProposalStoreConfig",
]
