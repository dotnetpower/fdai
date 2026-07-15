"""PostgreSQL pending incident proposal store with atomic consume."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from fdai.core.incident.intent import IncidentCreationProposal
from fdai.core.incident.proposal_store import (
    ProposalTakeResult,
    proposal_from_record,
    proposal_to_record,
)
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig

_KEY_PREFIX = "incident-proposal:"


class PostgresIncidentProposalStore:
    """Persist proposals in ``state_kv`` and consume with DELETE RETURNING."""

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresStateStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def save(
        self,
        *,
        operator_id: str,
        session_id: str,
        proposal: IncidentCreationProposal,
    ) -> None:
        key = _state_key(operator_id, session_id)
        if proposal.requested_by != operator_id:
            raise ValueError("incident proposal requester MUST match operator_id")
        payload = proposal_to_record(proposal)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await _set_statement_timeout(connection, self._config.statement_timeout_ms)
                await connection.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value,
                                  updated_at = NOW()
                    """,
                    (key, json.dumps(payload)),
                )

    async def take(
        self,
        *,
        operator_id: str,
        session_id: str,
        now: datetime,
    ) -> ProposalTakeResult:
        key = _state_key(operator_id, session_id)
        if now.tzinfo is None:
            raise ValueError("incident proposal now MUST be timezone-aware")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await _set_statement_timeout(connection, self._config.statement_timeout_ms)
                cursor = await connection.execute(
                    "DELETE FROM state_kv WHERE key = %s RETURNING value",
                    (key,),
                )
                row = await cursor.fetchone()
        if row is None:
            return ProposalTakeResult(status="missing")
        value = row["value"]
        if not isinstance(value, dict):
            raise RuntimeError("incident proposal state value is not a JSON object")
        proposal = proposal_from_record(value)
        if proposal.requested_by != operator_id:
            raise RuntimeError("incident proposal requester does not match persistence key")
        if now > proposal.expires_at:
            return ProposalTakeResult(status="expired")
        return ProposalTakeResult(status="found", proposal=proposal)


def _state_key(operator_id: str, session_id: str) -> str:
    if not operator_id or not session_id:
        raise ValueError("incident proposal operator_id and session_id MUST be non-empty")
    digest = hashlib.sha256(f"{operator_id}\0{session_id}".encode()).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


async def _set_statement_timeout(
    connection: psycopg.AsyncConnection[object], timeout_ms: int
) -> None:
    await connection.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


__all__ = ["PostgresIncidentProposalStore"]
