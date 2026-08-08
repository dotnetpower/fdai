"""PostgreSQL persistence for reviewed runtime skill proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.skills import (
    SkillProposal,
    SkillProposalState,
    SkillWorkshopError,
)

_COLUMNS: Final = (
    "proposal_id, skill_name, content_hash, markdown, proposed_by_agent, created_at, "
    "state, reviewed_by, review_reason, reviewed_at"
)


@dataclass(frozen=True, slots=True)
class PostgresSkillProposalStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresSkillProposalStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresSkillProposalStoreConfig timeouts MUST be positive")


class PostgresSkillProposalStore:
    """Durable proposal records with atomic expected-state transitions."""

    def __init__(self, *, config: PostgresSkillProposalStoreConfig) -> None:
        self._config = config

    async def create(self, proposal: SkillProposal) -> SkillProposal:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO skill_proposal ({_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL)
                ON CONFLICT (proposal_id) DO NOTHING
                RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    proposal.proposal_id,
                    proposal.skill_name,
                    proposal.content_hash,
                    proposal.markdown,
                    proposal.proposed_by_agent,
                    proposal.created_at,
                    proposal.state.value,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                existing_cursor = await connection.execute(
                    f"SELECT {_COLUMNS} FROM skill_proposal WHERE proposal_id = %s",  # noqa: S608
                    (proposal.proposal_id,),
                )
                row = await existing_cursor.fetchone()
        if row is None:
            raise RuntimeError("skill proposal insert returned no row")
        existing = _row_to_proposal(row)
        if existing.content_hash != proposal.content_hash:
            raise SkillWorkshopError("skill proposal id collision")
        return existing

    async def get(self, proposal_id: str) -> SkillProposal:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM skill_proposal WHERE proposal_id = %s",  # noqa: S608
                (proposal_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise SkillWorkshopError(f"skill proposal {proposal_id!r} was not found")
        return _row_to_proposal(row)

    async def transition(
        self,
        proposal: SkillProposal,
        *,
        expected_state: SkillProposalState,
    ) -> SkillProposal | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE skill_proposal
                   SET state = %s, reviewed_by = %s, review_reason = %s, reviewed_at = %s,
                       updated_at = now()
                 WHERE proposal_id = %s AND state = %s
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    proposal.state.value,
                    proposal.reviewed_by,
                    proposal.review_reason,
                    proposal.reviewed_at,
                    proposal.proposal_id,
                    expected_state.value,
                ),
            )
            row = await cursor.fetchone()
        return _row_to_proposal(row) if row is not None else None

    async def list(self) -> tuple[SkillProposal, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM skill_proposal ORDER BY proposal_id"  # noqa: S608
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


def _row_to_proposal(row: dict[str, Any]) -> SkillProposal:
    return SkillProposal(
        proposal_id=str(row["proposal_id"]),
        skill_name=str(row["skill_name"]),
        content_hash=str(row["content_hash"]),
        markdown=bytes(row["markdown"]),
        proposed_by_agent=str(row["proposed_by_agent"]),
        created_at=row["created_at"],
        state=SkillProposalState(str(row["state"])),
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        review_reason=(str(row["review_reason"]) if row["review_reason"] is not None else None),
        reviewed_at=row["reviewed_at"],
    )


__all__ = ["PostgresSkillProposalStore", "PostgresSkillProposalStoreConfig"]
