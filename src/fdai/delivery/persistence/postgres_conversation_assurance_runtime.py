"""PostgreSQL runtime registry for promoted conversation policies."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.conversation_assurance.lifecycle import ChatPolicyPublisher
from fdai.core.conversation_assurance.promotion import (
    ChatPolicyCandidate,
    ChatPolicyTarget,
    PolicyStage,
    PolicyTransition,
)
from fdai.core.conversation_assurance.runtime_policy import (
    BASE_POLICY_DIGEST,
    AppliedChatPolicy,
    ConversationPolicyRuntime,
    policy_is_assigned,
)


@dataclass(frozen=True, slots=True)
class PostgresConversationPolicyRuntimeConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("conversation policy runtime dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("conversation policy runtime timeouts MUST be positive")


class PostgresConversationPolicyRuntime(ChatPolicyPublisher, ConversationPolicyRuntime):
    """Publish, resolve, and restore one scoped policy per target."""

    def __init__(self, *, config: PostgresConversationPolicyRuntimeConfig) -> None:
        self._config = config

    async def current_digest(
        self,
        *,
        principal_scope: str,
        target: ChatPolicyTarget,
    ) -> str:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            current = await self._current(connection, principal_scope, target, lock=False)
        return current.policy_digest if current is not None else BASE_POLICY_DIGEST

    async def resolve(
        self,
        *,
        principal_scope: str,
        target: ChatPolicyTarget,
        assignment_key: str,
    ) -> AppliedChatPolicy | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            current = await self._current(connection, principal_scope, target, lock=False)
        if current is None or not policy_is_assigned(current, assignment_key=assignment_key):
            return None
        return current

    async def publish(
        self,
        candidate: ChatPolicyCandidate,
        transition: PolicyTransition,
    ) -> None:
        if candidate.policy_text is None:
            raise ValueError("digest-only policy candidate cannot be published")
        if candidate.candidate_id != transition.candidate_id:
            raise ValueError("policy transition candidate mismatch")
        publication_key = _publication_key(candidate, transition)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            before = await self._current(
                connection, candidate.principal_scope, candidate.target, lock=True
            )
            after = await self._desired_state(connection, candidate, transition, before)
            existing = await self._publication(connection, publication_key)
            if existing is not None:
                if existing != (_state_mapping(before), _state_mapping(after)):
                    raise ValueError("policy publication key belongs to different content")
                return
            await connection.execute(
                "INSERT INTO conversation_assurance_policy_publication "
                "(publication_key, principal_scope, target, before_state, after_state) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    publication_key,
                    candidate.principal_scope,
                    candidate.target.value,
                    Jsonb(_state_mapping(before)),
                    Jsonb(_state_mapping(after)),
                ),
            )
            await self._write_current(
                connection,
                principal_scope=candidate.principal_scope,
                target=candidate.target,
                policy=after,
            )

    async def restore(
        self,
        candidate: ChatPolicyCandidate,
        transition: PolicyTransition,
    ) -> None:
        publication_key = _publication_key(candidate, transition)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            snapshot = await self._publication(connection, publication_key)
            if snapshot is None:
                raise LookupError("policy publication snapshot is unavailable")
            before_raw, after_raw = snapshot
            current = await self._current(
                connection, candidate.principal_scope, candidate.target, lock=True
            )
            if _state_mapping(current) != after_raw:
                raise ValueError("policy runtime changed after publication")
            await self._write_current(
                connection,
                principal_scope=candidate.principal_scope,
                target=candidate.target,
                policy=_state(before_raw),
            )

    async def _desired_state(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        candidate: ChatPolicyCandidate,
        transition: PolicyTransition,
        before: AppliedChatPolicy | None,
    ) -> AppliedChatPolicy | None:
        if transition.to_stage is PolicyStage.ROLLED_BACK:
            if candidate.incumbent_policy_digest == BASE_POLICY_DIGEST:
                return None
            cursor = await connection.execute(
                "SELECT candidate_id, principal_scope, target, policy_digest, policy_text "
                "FROM conversation_assurance_policy_candidate "
                "WHERE principal_scope = %s AND target = %s AND policy_digest = %s "
                "AND policy_text IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                (
                    candidate.principal_scope,
                    candidate.target.value,
                    candidate.incumbent_policy_digest,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise LookupError("incumbent policy artifact is unavailable")
            return _policy(row, stage=PolicyStage.ACTIVE)
        current_digest = before.policy_digest if before is not None else BASE_POLICY_DIGEST
        if before is None or before.candidate_id != candidate.candidate_id:
            if current_digest != candidate.incumbent_policy_digest:
                raise ValueError("policy candidate incumbent digest is stale")
        if candidate.policy_text is None:
            raise ValueError("digest-only policy candidate cannot be published")
        return AppliedChatPolicy(
            candidate_id=candidate.candidate_id,
            principal_scope=candidate.principal_scope,
            target=candidate.target,
            policy_digest=candidate.policy_digest,
            policy_text=candidate.policy_text,
            stage=transition.to_stage,
        )

    async def _publication(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        publication_key: str,
    ) -> tuple[dict[str, object] | None, dict[str, object] | None] | None:
        cursor = await connection.execute(
            "SELECT before_state, after_state "
            "FROM conversation_assurance_policy_publication WHERE publication_key = %s",
            (publication_key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row["before_state"], row["after_state"]

    async def _current(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        principal_scope: str,
        target: ChatPolicyTarget,
        *,
        lock: bool,
    ) -> AppliedChatPolicy | None:
        suffix = " FOR UPDATE" if lock else ""
        cursor = await connection.execute(
            "SELECT candidate_id, principal_scope, target, policy_digest, policy_text, stage "
            "FROM conversation_assurance_policy_runtime "
            "WHERE principal_scope = %s AND target = %s" + suffix,
            (principal_scope, target.value),
        )
        row = await cursor.fetchone()
        return _policy(row) if row is not None else None

    async def _write_current(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        principal_scope: str,
        target: ChatPolicyTarget,
        policy: AppliedChatPolicy | None,
    ) -> None:
        if policy is None:
            await connection.execute(
                "DELETE FROM conversation_assurance_policy_runtime "
                "WHERE principal_scope = %s AND target = %s",
                (principal_scope, target.value),
            )
            return
        await connection.execute(
            "INSERT INTO conversation_assurance_policy_runtime "
            "(principal_scope, target, candidate_id, policy_digest, policy_text, stage) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (principal_scope, target) DO UPDATE SET "
            "candidate_id = excluded.candidate_id, policy_digest = excluded.policy_digest, "
            "policy_text = excluded.policy_text, stage = excluded.stage, updated_at = now()",
            (
                policy.principal_scope,
                policy.target.value,
                policy.candidate_id,
                policy.policy_digest,
                policy.policy_text,
                policy.stage.value,
            ),
        )

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


def _policy(
    row: dict[str, Any],
    *,
    stage: PolicyStage | None = None,
) -> AppliedChatPolicy:
    return AppliedChatPolicy(
        candidate_id=str(row["candidate_id"]),
        principal_scope=str(row["principal_scope"]),
        target=ChatPolicyTarget(str(row["target"])),
        policy_digest=str(row["policy_digest"]),
        policy_text=str(row["policy_text"]),
        stage=stage or PolicyStage(str(row["stage"])),
    )


def _state_mapping(policy: AppliedChatPolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    raw = asdict(policy)
    raw["target"] = policy.target.value
    raw["stage"] = policy.stage.value
    return raw


def _state(raw: dict[str, object] | None) -> AppliedChatPolicy | None:
    if raw is None:
        return None
    return AppliedChatPolicy(
        candidate_id=str(raw["candidate_id"]),
        principal_scope=str(raw["principal_scope"]),
        target=ChatPolicyTarget(str(raw["target"])),
        policy_digest=str(raw["policy_digest"]),
        policy_text=str(raw["policy_text"]),
        stage=PolicyStage(str(raw["stage"])),
    )


def _publication_key(candidate: ChatPolicyCandidate, transition: PolicyTransition) -> str:
    material = "\0".join(
        (
            candidate.principal_scope,
            candidate.target.value,
            candidate.candidate_id,
            transition.from_stage.value,
            transition.to_stage.value,
            transition.evidence_digest,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


__all__ = [
    "PostgresConversationPolicyRuntime",
    "PostgresConversationPolicyRuntimeConfig",
]
