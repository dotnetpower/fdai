"""Append-only PostgreSQL retention for derived dialogue-state snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from fdai_service_contracts.dialogue_state import DialogueState
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn


class DialogueSnapshotStoreError(RuntimeError):
    """The durable snapshot store is unavailable or returned malformed state."""


@dataclass(frozen=True, slots=True)
class PostgresDialogueSnapshotConfig:
    dsn: str
    connect_timeout_s: float = 5.0
    statement_timeout_ms: int = 5000


def dialogue_snapshot_id(state: DialogueState) -> str:
    """Identify a snapshot by its compacted range and verified content, not the sliding window."""

    payload = state.model_dump(mode="json", exclude={"kept_turn_ids", "source_turn_count"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


class PostgresDialogueSnapshotStore:
    """Insert and read principal-scoped snapshots; rows are immutable once written."""

    def __init__(self, config: PostgresDialogueSnapshotConfig) -> None:
        self._config = config

    async def append(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        state: DialogueState,
        recorded_at: datetime,
    ) -> bool:
        """Return True when a new row was written; False for a duplicate or empty range."""

        if not principal_id or not conversation_id:
            raise ValueError("dialogue snapshots require a principal and conversation")
        if not state.compacted_turn_ids or state.compacted_digest is None:
            return False
        rows = await self._execute(
            """
            INSERT INTO conversation_dialogue_snapshot
                (principal_id, conversation_id, snapshot_id, tier, source_turn_count,
                 compacted_turn_count, compacted_digest, state, recorded_at)
            VALUES (%(principal_id)s, %(conversation_id)s, %(snapshot_id)s, %(tier)s,
                    %(source_turn_count)s, %(compacted_turn_count)s, %(compacted_digest)s,
                    %(state)s, %(recorded_at)s)
            ON CONFLICT (principal_id, conversation_id, snapshot_id) DO NOTHING
            RETURNING snapshot_id
            """,
            {
                "principal_id": principal_id,
                "conversation_id": conversation_id,
                "snapshot_id": dialogue_snapshot_id(state),
                "tier": state.tier,
                "source_turn_count": state.source_turn_count,
                "compacted_turn_count": len(state.compacted_turn_ids),
                "compacted_digest": state.compacted_digest,
                "state": Jsonb(state.model_dump(mode="json")),
                "recorded_at": recorded_at,
            },
        )
        return bool(rows)

    async def latest(self, *, principal_id: str, conversation_id: str) -> DialogueState | None:
        """Return the newest snapshot of one principal-owned conversation."""

        rows = await self._execute(
            """
            SELECT state FROM conversation_dialogue_snapshot
             WHERE principal_id = %(principal_id)s AND conversation_id = %(conversation_id)s
             ORDER BY recorded_at DESC, snapshot_id DESC LIMIT 1
            """,
            {"principal_id": principal_id, "conversation_id": conversation_id},
        )
        if not rows:
            return None
        try:
            return DialogueState.model_validate(rows[0]["state"])
        except ValueError as exc:
            raise DialogueSnapshotStoreError("stored dialogue snapshot is malformed") from exc

    async def _execute(self, statement: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                normalize_psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=int(self._config.connect_timeout_s),
                autocommit=True,
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, false)",
                    (str(self._config.statement_timeout_ms),),
                )
                cursor = await connection.execute(statement, parameters)
                return list(await cursor.fetchall())
        except psycopg.Error as exc:
            raise DialogueSnapshotStoreError("dialogue snapshot storage is unavailable") from exc


__all__ = [
    "DialogueSnapshotStoreError",
    "PostgresDialogueSnapshotConfig",
    "PostgresDialogueSnapshotStore",
    "dialogue_snapshot_id",
]
