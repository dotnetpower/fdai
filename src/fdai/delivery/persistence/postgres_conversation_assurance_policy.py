"""PostgreSQL policy-candidate lifecycle store for conversation assurance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.conversation_assurance import (
    ChatPolicyCandidate,
    ChatPolicyTarget,
    PolicyStage,
    PolicyTransition,
)

_CANDIDATE_COLUMNS: Final = (
    "candidate_id, principal_scope, cluster_id, target, policy_digest, "
    "incumbent_policy_digest, stage"
)
_TRANSITION_COLUMNS: Final = "candidate_id, from_stage, to_stage, reasons"


@dataclass(frozen=True, slots=True)
class PostgresConversationPolicyCandidateStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("policy candidate store dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("policy candidate store timeouts MUST be positive")


class PostgresConversationPolicyCandidateStore:
    """Persist immutable candidates and serialized stage transitions."""

    def __init__(self, *, config: PostgresConversationPolicyCandidateStoreConfig) -> None:
        self._config = config

    async def append_candidate(self, candidate: ChatPolicyCandidate) -> bool:
        if candidate.stage is not PolicyStage.SHADOW:
            raise ValueError("new policy candidates MUST start in shadow")
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO conversation_assurance_policy_candidate ({_CANDIDATE_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (candidate_id) DO NOTHING
                RETURNING candidate_id
                """,  # noqa: S608 - columns are module constants
                _candidate_values(candidate),
            )
            if await cursor.fetchone() is not None:
                return True
            existing = await self._select_candidate(
                connection,
                principal_scope=candidate.principal_scope,
                candidate_id=candidate.candidate_id,
            )
            if existing != candidate:
                raise ValueError("candidate id already belongs to different content")
            return False

    async def get_candidate(
        self,
        *,
        principal_scope: str,
        candidate_id: str,
    ) -> ChatPolicyCandidate | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            return await self._select_candidate(
                connection,
                principal_scope=principal_scope,
                candidate_id=candidate_id,
            )

    async def apply_transition(
        self,
        *,
        principal_scope: str,
        transition: PolicyTransition,
    ) -> ChatPolicyCandidate:
        key = _transition_key(transition)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            candidate_cursor = await connection.execute(
                f"SELECT {_CANDIDATE_COLUMNS} "  # noqa: S608 - columns are module constants
                "FROM conversation_assurance_policy_candidate "
                "WHERE principal_scope = %s AND candidate_id = %s FOR UPDATE",
                (principal_scope, transition.candidate_id),
            )
            candidate_row = await candidate_cursor.fetchone()
            if candidate_row is None:
                raise LookupError("policy candidate is unavailable in the principal scope")
            candidate = _candidate(candidate_row)
            replay_cursor = await connection.execute(
                f"SELECT {_TRANSITION_COLUMNS} "  # noqa: S608 - columns are module constants
                "FROM conversation_assurance_policy_transition WHERE transition_key = %s",
                (key,),
            )
            replay_row = await replay_cursor.fetchone()
            if replay_row is not None:
                if _transition(replay_row) != transition:
                    raise ValueError("policy transition key belongs to different content")
                return candidate
            if candidate.stage is not transition.from_stage:
                raise ValueError("policy transition from_stage is stale")
            await connection.execute(
                """
                INSERT INTO conversation_assurance_policy_transition (
                    transition_key, candidate_id, principal_scope,
                    from_stage, to_stage, reasons
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    key,
                    transition.candidate_id,
                    principal_scope,
                    transition.from_stage.value,
                    transition.to_stage.value,
                    list(transition.reasons),
                ),
            )
            update_cursor = await connection.execute(
                """
                UPDATE conversation_assurance_policy_candidate
                   SET stage = %s, updated_at = now()
                 WHERE principal_scope = %s AND candidate_id = %s AND stage = %s
                RETURNING candidate_id
                """,
                (
                    transition.to_stage.value,
                    principal_scope,
                    transition.candidate_id,
                    transition.from_stage.value,
                ),
            )
            if await update_cursor.fetchone() is None:
                raise RuntimeError("policy candidate stage changed during locked transition")
            return ChatPolicyCandidate(
                candidate_id=candidate.candidate_id,
                principal_scope=candidate.principal_scope,
                cluster_id=candidate.cluster_id,
                target=candidate.target,
                policy_digest=candidate.policy_digest,
                incumbent_policy_digest=candidate.incumbent_policy_digest,
                stage=transition.to_stage,
            )

    async def list_transitions(
        self,
        *,
        principal_scope: str,
        candidate_id: str,
        limit: int = 100,
    ) -> tuple[PolicyTransition, ...]:
        _require_limit(limit)
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_TRANSITION_COLUMNS} "  # noqa: S608 - columns are module constants
                "FROM conversation_assurance_policy_transition "
                "WHERE principal_scope = %s AND candidate_id = %s "
                "ORDER BY occurred_at DESC, transition_key DESC LIMIT %s",
                (principal_scope, candidate_id, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_transition(row) for row in reversed(rows))

    async def _select_candidate(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        principal_scope: str,
        candidate_id: str,
    ) -> ChatPolicyCandidate | None:
        cursor = await connection.execute(
            f"SELECT {_CANDIDATE_COLUMNS} "  # noqa: S608 - columns are module constants
            "FROM conversation_assurance_policy_candidate "
            "WHERE principal_scope = %s AND candidate_id = %s",
            (principal_scope, candidate_id),
        )
        row = await cursor.fetchone()
        return _candidate(row) if row is not None else None

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


def _candidate_values(candidate: ChatPolicyCandidate) -> tuple[str, ...]:
    return (
        candidate.candidate_id,
        candidate.principal_scope,
        candidate.cluster_id,
        candidate.target.value,
        candidate.policy_digest,
        candidate.incumbent_policy_digest,
        candidate.stage.value,
    )


def _candidate(row: dict[str, Any]) -> ChatPolicyCandidate:
    return ChatPolicyCandidate(
        candidate_id=str(row["candidate_id"]),
        principal_scope=str(row["principal_scope"]),
        cluster_id=str(row["cluster_id"]),
        target=ChatPolicyTarget(str(row["target"])),
        policy_digest=str(row["policy_digest"]),
        incumbent_policy_digest=str(row["incumbent_policy_digest"]),
        stage=PolicyStage(str(row["stage"])),
    )


def _transition(row: dict[str, Any]) -> PolicyTransition:
    return PolicyTransition(
        candidate_id=str(row["candidate_id"]),
        from_stage=PolicyStage(str(row["from_stage"])),
        to_stage=PolicyStage(str(row["to_stage"])),
        reasons=tuple(str(item) for item in row["reasons"]),
    )


def _transition_key(transition: PolicyTransition) -> str:
    material = "\0".join(
        (
            transition.candidate_id,
            transition.from_stage.value,
            transition.to_stage.value,
            *transition.reasons,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError("policy transition limit MUST be in [1, 1000]")


__all__ = [
    "PostgresConversationPolicyCandidateStore",
    "PostgresConversationPolicyCandidateStoreConfig",
]
