"""PostgreSQL adapters for principal-scoped conversations, preferences, and memory."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_user_context_projection_queue import (
    enqueue_projection_upsert,
)
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationStatus,
    ConversationTurnRecord,
    ConversationTurnRole,
    UserContextConflictError,
    UserMemoryCategory,
    UserMemoryFact,
    UserPreferenceRecord,
)


@dataclass(frozen=True, slots=True)
class PostgresUserContextStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresUserContextStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresUserContextStoreConfig timeouts MUST be positive")


class _PostgresBase:
    def __init__(self, *, config: PostgresUserContextStoreConfig) -> None:
        self._config: Final = config

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


class PostgresConversationHistoryStore(_PostgresBase):
    async def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO conversation_record "
                "(principal_id, conversation_id, channel_id, started_at, last_active, status) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (principal_id, conversation_id) DO NOTHING "
                "RETURNING principal_id",
                (
                    record.principal_id,
                    record.conversation_id,
                    record.channel_id,
                    record.started_at,
                    record.last_active,
                    record.status.value,
                ),
            )
            if await cursor.fetchone() is None:
                existing = await self.get_conversation(
                    principal_id=record.principal_id,
                    conversation_id=record.conversation_id,
                    connection=connection,
                )
                if existing is None or existing.channel_id != record.channel_id:
                    raise UserContextConflictError(
                        f"conversation {record.conversation_id!r} already exists"
                    )
                return existing
        return record

    async def get_conversation(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        connection: psycopg.AsyncConnection[Any] | None = None,
    ) -> ConversationRecord | None:
        if connection is not None:
            return await self._get_conversation(connection, principal_id, conversation_id)
        async with await self._connect() as own:
            await self._timeout(own)
            return await self._get_conversation(own, principal_id, conversation_id)

    async def _get_conversation(
        self,
        connection: psycopg.AsyncConnection[Any],
        principal_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None:
        cursor = await connection.execute(
            "SELECT principal_id, conversation_id, channel_id, started_at, last_active, status "
            "FROM conversation_record WHERE principal_id = %s AND conversation_id = %s",
            (principal_id, conversation_id),
        )
        row = await cursor.fetchone()
        return _conversation(row) if row is not None else None

    async def list_conversations(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        before_last_active: datetime | None = None,
        before_conversation_id: str | None = None,
    ) -> tuple[ConversationRecord, ...]:
        _limit(limit)
        if (before_last_active is None) != (before_conversation_id is None):
            raise ValueError("conversation cursor MUST be complete")
        async with await self._connect() as connection:
            await self._timeout(connection)
            if before_last_active is not None and before_conversation_id is not None:
                cursor = await connection.execute(
                    "SELECT principal_id, conversation_id, channel_id, started_at, "
                    "last_active, status FROM conversation_record WHERE principal_id = %s "
                    "AND (last_active, conversation_id) < (%s, %s) "
                    "ORDER BY last_active DESC, conversation_id DESC LIMIT %s",
                    (principal_id, before_last_active, before_conversation_id, limit),
                )
            else:
                cursor = await connection.execute(
                    "SELECT principal_id, conversation_id, channel_id, started_at, "
                    "last_active, status FROM conversation_record WHERE principal_id = %s "
                    "ORDER BY last_active DESC, conversation_id DESC LIMIT %s",
                    (principal_id, limit),
                )
            return tuple(_conversation(row) for row in await cursor.fetchall())

    async def append_turn(
        self,
        record: ConversationTurnRecord,
        *,
        allocate_index: bool = False,
    ) -> ConversationTurnRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            existing = await self._turn_by_idempotency_optional(connection, record)
            if existing is not None:
                if not _same_idempotent_turn(
                    existing,
                    record,
                    ignore_index=allocate_index,
                ):
                    raise UserContextConflictError(
                        f"turn idempotency key {record.idempotency_key!r} conflicts"
                    )
                return existing
            if allocate_index:
                allocated = await connection.execute(
                    "UPDATE conversation_record SET next_turn_index = next_turn_index + 1, "
                    "last_active = GREATEST(last_active, %s) "
                    "WHERE principal_id = %s AND conversation_id = %s "
                    "RETURNING next_turn_index - 1 AS turn_index",
                    (record.recorded_at, record.principal_id, record.conversation_id),
                )
                row = await allocated.fetchone()
                if row is None:
                    raise UserContextConflictError(
                        f"conversation {record.conversation_id!r} not found"
                    )
                record = replace(record, turn_index=int(row["turn_index"]))
            try:
                cursor = await connection.execute(
                    "INSERT INTO conversation_turn "
                    "(principal_id, conversation_id, turn_id, turn_index, role, content, "
                    "recorded_at, idempotency_key, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
                    "ON CONFLICT (principal_id, idempotency_key) DO NOTHING "
                    "RETURNING turn_id",
                    (
                        record.principal_id,
                        record.conversation_id,
                        record.turn_id,
                        record.turn_index,
                        record.role.value,
                        record.content,
                        record.recorded_at,
                        record.idempotency_key,
                        json.dumps(dict(record.metadata)),
                    ),
                )
            except (psycopg.errors.UniqueViolation, psycopg.errors.ForeignKeyViolation) as exc:
                raise UserContextConflictError(
                    "conversation turn conflicts with durable state"
                ) from exc
            if await cursor.fetchone() is None:
                existing = await self._turn_by_idempotency(connection, record)
                if not _same_idempotent_turn(
                    existing,
                    record,
                    ignore_index=allocate_index,
                ):
                    raise UserContextConflictError(
                        f"turn idempotency key {record.idempotency_key!r} conflicts"
                    )
                return existing
            await connection.execute(
                "UPDATE conversation_record SET last_active = GREATEST(last_active, %s) "
                "WHERE principal_id = %s AND conversation_id = %s",
                (record.recorded_at, record.principal_id, record.conversation_id),
            )
        return record

    async def get_turn_by_idempotency(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
    ) -> ConversationTurnRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, conversation_id, turn_id, turn_index, role, content, "
                "recorded_at, idempotency_key, metadata FROM conversation_turn "
                "WHERE principal_id = %s AND idempotency_key = %s",
                (principal_id, idempotency_key),
            )
            row = await cursor.fetchone()
            return _turn(row) if row is not None else None

    async def _turn_by_idempotency(
        self, connection: psycopg.AsyncConnection[Any], record: ConversationTurnRecord
    ) -> ConversationTurnRecord:
        cursor = await connection.execute(
            "SELECT principal_id, conversation_id, turn_id, turn_index, role, content, "
            "recorded_at, idempotency_key, metadata FROM conversation_turn "
            "WHERE principal_id = %s AND idempotency_key = %s",
            (record.principal_id, record.idempotency_key),
        )
        row = await cursor.fetchone()
        if row is None:
            raise UserContextConflictError("turn idempotency conflict has no persisted row")
        return _turn(row)

    async def _turn_by_idempotency_optional(
        self,
        connection: psycopg.AsyncConnection[Any],
        record: ConversationTurnRecord,
    ) -> ConversationTurnRecord | None:
        cursor = await connection.execute(
            "SELECT principal_id, conversation_id, turn_id, turn_index, role, content, "
            "recorded_at, idempotency_key, metadata FROM conversation_turn "
            "WHERE principal_id = %s AND idempotency_key = %s",
            (record.principal_id, record.idempotency_key),
        )
        row = await cursor.fetchone()
        return _turn(row) if row is not None else None

    async def list_turns(
        self, *, principal_id: str, conversation_id: str, limit: int = 200
    ) -> tuple[ConversationTurnRecord, ...]:
        _limit(limit)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, conversation_id, turn_id, turn_index, role, content, "
                "recorded_at, idempotency_key, metadata FROM conversation_turn "
                "WHERE principal_id = %s AND conversation_id = %s "
                "ORDER BY turn_index DESC LIMIT %s",
                (principal_id, conversation_id, limit),
            )
            rows = list(await cursor.fetchall())
        rows.reverse()
        return tuple(_turn(row) for row in rows)

    async def list_all_turns(
        self, *, principal_id: str, conversation_id: str
    ) -> tuple[ConversationTurnRecord, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, conversation_id, turn_id, turn_index, role, content, "
                "recorded_at, idempotency_key, metadata FROM conversation_turn "
                "WHERE principal_id = %s AND conversation_id = %s ORDER BY turn_index",
                (principal_id, conversation_id),
            )
            return tuple(_turn(row) for row in await cursor.fetchall())

    async def latest_operator_turn_ids(
        self,
        *,
        principal_id: str,
        conversation_ids: Sequence[str],
    ) -> Mapping[str, str]:
        if not conversation_ids:
            return {}
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT DISTINCT ON (conversation_id) conversation_id, turn_id "
                "FROM conversation_turn WHERE principal_id = %s "
                "AND conversation_id = ANY(%s) AND role = 'operator' "
                "ORDER BY conversation_id, turn_index DESC",
                (principal_id, list(conversation_ids)),
            )
            rows = await cursor.fetchall()
        return {str(row["conversation_id"]): str(row["turn_id"]) for row in rows}

    async def first_operator_questions(
        self,
        *,
        principal_id: str,
        conversation_ids: Sequence[str],
        max_chars: int,
    ) -> Mapping[str, str]:
        if max_chars < 4:
            raise ValueError("max_chars MUST be at least 4")
        if not conversation_ids:
            return {}
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT DISTINCT ON (conversation_id) conversation_id, "
                "CASE WHEN char_length(regexp_replace(btrim(content), '\\s+', ' ', 'g')) > %s "
                "THEN rtrim(left(regexp_replace(btrim(content), '\\s+', ' ', 'g'), %s)) || '...' "
                "ELSE regexp_replace(btrim(content), '\\s+', ' ', 'g') END AS content "
                "FROM conversation_turn WHERE principal_id = %s "
                "AND conversation_id = ANY(%s) AND role = 'operator' "
                "ORDER BY conversation_id, turn_index",
                (max_chars, max_chars - 3, principal_id, list(conversation_ids)),
            )
            rows = await cursor.fetchall()
        return {str(row["conversation_id"]): str(row["content"]) for row in rows}

    async def delete_conversation(self, *, principal_id: str, conversation_id: str) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "INSERT INTO user_context_projection_delete_queue (object_id) "
                "SELECT 'conversation:' || %s || ':' || %s "
                "WHERE EXISTS (SELECT 1 FROM conversation_record "
                "WHERE principal_id = %s AND conversation_id = %s) "
                "UNION SELECT 'turn:' || principal_id || ':' || turn_id "
                "FROM conversation_turn WHERE principal_id = %s AND conversation_id = %s "
                "UNION SELECT 'policy:' || principal_id || ':' || policy_id "
                "FROM conversation_policy WHERE principal_id = %s AND source_turn_id IN "
                "(SELECT turn_id FROM conversation_turn WHERE principal_id = %s "
                "AND conversation_id = %s) "
                "UNION SELECT 'memory:' || principal_id || ':' || memory_id "
                "FROM user_memory_fact WHERE principal_id = %s AND source_turn_id IN "
                "(SELECT turn_id FROM conversation_turn WHERE principal_id = %s "
                "AND conversation_id = %s) ON CONFLICT (object_id) DO NOTHING",
                (
                    principal_id,
                    conversation_id,
                    principal_id,
                    conversation_id,
                    principal_id,
                    conversation_id,
                    principal_id,
                    principal_id,
                    conversation_id,
                    principal_id,
                    principal_id,
                    conversation_id,
                ),
            )
            cursor = await connection.execute(
                "DELETE FROM conversation_record WHERE principal_id = %s "
                "AND conversation_id = %s RETURNING conversation_id",
                (principal_id, conversation_id),
            )
            return await cursor.fetchone() is not None

    async def purge_inactive(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> tuple[ConversationRecord, ...]:
        _limit(limit)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH selected AS ("
                "SELECT principal_id, conversation_id FROM conversation_record "
                "WHERE last_active < %s ORDER BY last_active, conversation_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s"
                ") DELETE FROM conversation_record AS conversation "
                "USING selected WHERE conversation.principal_id = selected.principal_id "
                "AND conversation.conversation_id = selected.conversation_id "
                "RETURNING conversation.principal_id, conversation.conversation_id, "
                "conversation.channel_id, conversation.started_at, "
                "conversation.last_active, conversation.status",
                (before, limit),
            )
            return tuple(_conversation(row) for row in await cursor.fetchall())


def _same_idempotent_turn(
    existing: ConversationTurnRecord,
    candidate: ConversationTurnRecord,
    *,
    ignore_index: bool,
) -> bool:
    candidate = replace(candidate, recorded_at=existing.recorded_at)
    if ignore_index:
        candidate = replace(candidate, turn_index=existing.turn_index)
    return existing == candidate


class PostgresUserPreferenceStore(_PostgresBase):
    async def get(self, *, principal_id: str) -> UserPreferenceRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, locale, verbosity, answer_detail, answer_format, "
                "answer_preferences_enabled, answer_intent_detail, answer_intent_format, "
                "timezone, share_with_learner, "
                "revision, updated_at FROM user_preference WHERE principal_id = %s",
                (principal_id,),
            )
            row = await cursor.fetchone()
        return _preference(row) if row is not None else None

    async def put(
        self,
        record: UserPreferenceRecord,
        *,
        expected_revision: int | None = None,
    ) -> UserPreferenceRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT revision FROM user_preference WHERE principal_id = %s FOR UPDATE",
                (record.principal_id,),
            )
            row = await cursor.fetchone()
            current = int(row["revision"]) if row is not None else 0
            if expected_revision is not None and expected_revision != current:
                raise UserContextConflictError(
                    f"preference revision mismatch: expected {expected_revision}, current {current}"
                )
            revision = current + 1
            updated_at = record.updated_at or datetime.now().astimezone()
            await connection.execute(
                "INSERT INTO user_preference "
                "(principal_id, locale, verbosity, answer_detail, answer_format, "
                "answer_preferences_enabled, answer_intent_detail, answer_intent_format, "
                "timezone, share_with_learner, revision, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s) "
                "ON CONFLICT (principal_id) DO UPDATE SET locale = EXCLUDED.locale, "
                "verbosity = EXCLUDED.verbosity, timezone = EXCLUDED.timezone, "
                "answer_detail = EXCLUDED.answer_detail, "
                "answer_format = EXCLUDED.answer_format, "
                "answer_preferences_enabled = EXCLUDED.answer_preferences_enabled, "
                "answer_intent_detail = EXCLUDED.answer_intent_detail, "
                "answer_intent_format = EXCLUDED.answer_intent_format, "
                "share_with_learner = EXCLUDED.share_with_learner, "
                "revision = EXCLUDED.revision, updated_at = EXCLUDED.updated_at",
                (
                    record.principal_id,
                    record.locale,
                    record.verbosity,
                    record.answer_detail,
                    record.answer_format,
                    record.answer_preferences_enabled,
                    json.dumps(dict(record.answer_intent_detail)),
                    json.dumps(dict(record.answer_intent_format)),
                    record.timezone,
                    record.share_with_learner,
                    revision,
                    updated_at,
                ),
            )
            await enqueue_projection_upsert(
                connection,
                projection_kind="preference",
                principal_id=record.principal_id,
                record_id=record.principal_id,
            )
        return UserPreferenceRecord(
            principal_id=record.principal_id,
            locale=record.locale,
            verbosity=record.verbosity,
            answer_detail=record.answer_detail,
            answer_format=record.answer_format,
            answer_preferences_enabled=record.answer_preferences_enabled,
            answer_intent_detail=dict(record.answer_intent_detail),
            answer_intent_format=dict(record.answer_intent_format),
            timezone=record.timezone,
            share_with_learner=record.share_with_learner,
            revision=revision,
            updated_at=updated_at,
        )

    async def delete(self, *, principal_id: str) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO user_context_projection_delete_queue (object_id) "
                "SELECT 'preference:' || principal_id FROM user_preference "
                "WHERE principal_id = %s ON CONFLICT (object_id) DO NOTHING",
                (principal_id,),
            )
            cursor = await connection.execute(
                "DELETE FROM user_preference WHERE principal_id = %s RETURNING principal_id",
                (principal_id,),
            )
            return await cursor.fetchone() is not None


class PostgresUserMemoryStore(_PostgresBase):
    async def create(self, fact: UserMemoryFact) -> UserMemoryFact:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO user_memory_fact "
                    "(principal_id, memory_id, category, body, source_turn_id, consented_at, "
                    "created_at, expires_at, superseded_by) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        fact.principal_id,
                        fact.memory_id,
                        fact.category.value,
                        fact.body,
                        fact.source_turn_id,
                        fact.consented_at,
                        fact.created_at,
                        fact.expires_at,
                        fact.superseded_by,
                    ),
                )
                await enqueue_projection_upsert(
                    connection,
                    projection_kind="memory",
                    principal_id=fact.principal_id,
                    record_id=fact.memory_id,
                )
            except (psycopg.errors.UniqueViolation, psycopg.errors.ForeignKeyViolation) as exc:
                raise UserContextConflictError(f"memory {fact.memory_id!r} conflicts") from exc
        return fact

    async def list_active(
        self, *, principal_id: str, now: datetime, limit: int = 100
    ) -> tuple[UserMemoryFact, ...]:
        _limit(limit)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, memory_id, category, body, source_turn_id, "
                "consented_at, created_at, expires_at, superseded_by FROM user_memory_fact "
                "WHERE principal_id = %s AND superseded_by IS NULL "
                "AND (expires_at IS NULL OR expires_at > %s) "
                "ORDER BY created_at, memory_id LIMIT %s",
                (principal_id, now, limit),
            )
            return tuple(_memory(row) for row in await cursor.fetchall())

    async def supersede(self, *, principal_id: str, memory_id: str, superseded_by: str) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE user_memory_fact SET superseded_by = %s "
                "WHERE principal_id = %s AND memory_id = %s AND superseded_by IS NULL "
                "AND EXISTS (SELECT 1 FROM user_memory_fact replacement "
                "WHERE replacement.principal_id = %s AND replacement.memory_id = %s) "
                "RETURNING memory_id",
                (superseded_by, principal_id, memory_id, principal_id, superseded_by),
            )
            if await cursor.fetchone() is None:
                raise LookupError(f"memory {memory_id!r} or replacement not found")

    async def delete(self, *, principal_id: str, memory_id: str) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO user_context_projection_delete_queue (object_id) "
                "SELECT 'memory:' || principal_id || ':' || memory_id "
                "FROM user_memory_fact WHERE principal_id = %s AND memory_id = %s "
                "ON CONFLICT (object_id) DO NOTHING",
                (principal_id, memory_id),
            )
            cursor = await connection.execute(
                "DELETE FROM user_memory_fact WHERE principal_id = %s AND memory_id = %s "
                "RETURNING memory_id",
                (principal_id, memory_id),
            )
            return await cursor.fetchone() is not None

    async def purge_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[UserMemoryFact, ...]:
        _limit(limit)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH selected AS ("
                "SELECT principal_id, memory_id FROM user_memory_fact "
                "WHERE expires_at IS NOT NULL AND expires_at <= %s "
                "ORDER BY expires_at, memory_id FOR UPDATE SKIP LOCKED LIMIT %s"
                ") DELETE FROM user_memory_fact AS memory USING selected "
                "WHERE memory.principal_id = selected.principal_id "
                "AND memory.memory_id = selected.memory_id "
                "RETURNING memory.principal_id, memory.memory_id, memory.category, "
                "memory.body, memory.source_turn_id, memory.consented_at, "
                "memory.created_at, memory.expires_at, memory.superseded_by",
                (now, limit),
            )
            return tuple(_memory(row) for row in await cursor.fetchall())


def _conversation(row: dict[str, Any]) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=str(row["conversation_id"]),
        principal_id=str(row["principal_id"]),
        channel_id=str(row["channel_id"]),
        started_at=row["started_at"],
        last_active=row["last_active"],
        status=ConversationStatus(str(row["status"])),
    )


def _turn(row: dict[str, Any]) -> ConversationTurnRecord:
    return ConversationTurnRecord(
        turn_id=str(row["turn_id"]),
        conversation_id=str(row["conversation_id"]),
        principal_id=str(row["principal_id"]),
        turn_index=int(row["turn_index"]),
        role=ConversationTurnRole(str(row["role"])),
        content=str(row["content"]),
        recorded_at=row["recorded_at"],
        idempotency_key=str(row["idempotency_key"]),
        metadata=dict(row["metadata"]),
    )


def _preference(row: dict[str, Any]) -> UserPreferenceRecord:
    return UserPreferenceRecord(
        principal_id=str(row["principal_id"]),
        locale=str(row["locale"]),
        verbosity=str(row["verbosity"]),
        answer_detail=str(row["answer_detail"]),
        answer_format=str(row["answer_format"]),
        answer_preferences_enabled=bool(row["answer_preferences_enabled"]),
        answer_intent_detail=dict(row["answer_intent_detail"]),
        answer_intent_format=dict(row["answer_intent_format"]),
        timezone=str(row["timezone"]) if row["timezone"] is not None else None,
        share_with_learner=bool(row["share_with_learner"]),
        revision=int(row["revision"]),
        updated_at=row["updated_at"],
    )


def _memory(row: dict[str, Any]) -> UserMemoryFact:
    return UserMemoryFact(
        memory_id=str(row["memory_id"]),
        principal_id=str(row["principal_id"]),
        category=UserMemoryCategory(str(row["category"])),
        body=str(row["body"]),
        source_turn_id=str(row["source_turn_id"]),
        consented_at=row["consented_at"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        superseded_by=(str(row["superseded_by"]) if row["superseded_by"] else None),
    )


def _limit(value: int) -> None:
    if not 1 <= value <= 1000:
        raise ValueError("limit MUST be in [1, 1000]")


__all__ = [
    "PostgresConversationHistoryStore",
    "PostgresUserContextStoreConfig",
    "PostgresUserMemoryStore",
    "PostgresUserPreferenceStore",
]
