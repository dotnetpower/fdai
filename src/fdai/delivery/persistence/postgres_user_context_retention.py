"""Retention cleanup and durable ontology-deletion retry queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_user_context import PostgresUserContextStoreConfig


@dataclass(frozen=True, slots=True)
class UserContextRetentionReport:
    conversations: int
    memories: int
    briefing_runs: int
    queued_projection_deletes: int
    conversation_images: int = 0


@dataclass(frozen=True, slots=True)
class ProjectionDeleteJob:
    object_id: str
    attempts: int


class PostgresUserContextRetention:
    def __init__(self, *, config: PostgresUserContextStoreConfig) -> None:
        self._config = config

    async def purge(
        self,
        *,
        now: datetime,
        conversation_before: datetime,
        briefing_before: datetime,
        limit: int = 500,
    ) -> UserContextRetentionReport:
        if not 1 <= limit <= 5000:
            raise ValueError("limit MUST be in [1, 5000]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            conversation_rows = await self._conversation_rows(
                connection, before=conversation_before, limit=limit
            )
            expired_images = await connection.execute(
                "WITH selected AS (SELECT principal_id, conversation_id, image_id "
                "FROM conversation_image WHERE expires_at <= %s "
                "ORDER BY expires_at, image_id FOR UPDATE SKIP LOCKED LIMIT %s) "
                "DELETE FROM conversation_image AS image USING selected "
                "WHERE image.principal_id = selected.principal_id "
                "AND image.conversation_id = selected.conversation_id "
                "AND image.image_id = selected.image_id RETURNING image.image_id",
                (now, limit),
            )
            expired_image_rows = await expired_images.fetchall()
            conversation_keys = [
                (str(row["principal_id"]), str(row["conversation_id"])) for row in conversation_rows
            ]
            object_ids: set[str] = set()
            for principal_id, conversation_id in conversation_keys:
                object_ids.add(f"conversation:{principal_id}:{conversation_id}")
                related = await connection.execute(
                    "SELECT turn_id FROM conversation_turn WHERE principal_id = %s "
                    "AND conversation_id = %s",
                    (principal_id, conversation_id),
                )
                object_ids.update(
                    f"turn:{principal_id}:{row['turn_id']}" for row in await related.fetchall()
                )
                policies = await connection.execute(
                    "SELECT policy_id FROM conversation_policy WHERE principal_id = %s "
                    "AND source_turn_id IN (SELECT turn_id FROM conversation_turn "
                    "WHERE principal_id = %s AND conversation_id = %s)",
                    (principal_id, principal_id, conversation_id),
                )
                object_ids.update(
                    f"policy:{principal_id}:{row['policy_id']}" for row in await policies.fetchall()
                )
                memories = await connection.execute(
                    "SELECT memory_id FROM user_memory_fact WHERE principal_id = %s "
                    "AND source_turn_id IN (SELECT turn_id FROM conversation_turn "
                    "WHERE principal_id = %s AND conversation_id = %s)",
                    (principal_id, principal_id, conversation_id),
                )
                object_ids.update(
                    f"memory:{principal_id}:{row['memory_id']}" for row in await memories.fetchall()
                )
            if conversation_keys:
                async with connection.cursor() as batch:
                    await batch.executemany(
                        "DELETE FROM conversation_record WHERE principal_id = %s "
                        "AND conversation_id = %s",
                        conversation_keys,
                    )

            expired = await connection.execute(
                "WITH selected AS (SELECT principal_id, memory_id FROM user_memory_fact "
                "WHERE expires_at IS NOT NULL AND expires_at <= %s "
                "ORDER BY expires_at, memory_id FOR UPDATE SKIP LOCKED LIMIT %s) "
                "DELETE FROM user_memory_fact AS memory USING selected "
                "WHERE memory.principal_id = selected.principal_id "
                "AND memory.memory_id = selected.memory_id "
                "RETURNING memory.principal_id, memory.memory_id",
                (now, limit),
            )
            expired_rows = await expired.fetchall()
            object_ids.update(
                f"memory:{row['principal_id']}:{row['memory_id']}" for row in expired_rows
            )

            briefing = await connection.execute(
                "WITH selected AS (SELECT principal_id, run_id FROM briefing_run "
                "WHERE started_at < %s ORDER BY started_at, run_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s) "
                "DELETE FROM briefing_run AS run USING selected "
                "WHERE run.principal_id = selected.principal_id "
                "AND run.run_id = selected.run_id "
                "RETURNING run.principal_id, run.run_id",
                (briefing_before, limit),
            )
            briefing_rows = await briefing.fetchall()
            object_ids.update(
                f"briefing-run:{row['principal_id']}:{row['run_id']}" for row in briefing_rows
            )
            if object_ids:
                async with connection.cursor() as batch:
                    await batch.executemany(
                        "INSERT INTO user_context_projection_delete_queue (object_id) "
                        "VALUES (%s) ON CONFLICT (object_id) DO NOTHING",
                        [(object_id,) for object_id in sorted(object_ids)],
                    )
        return UserContextRetentionReport(
            conversations=len(conversation_keys),
            memories=len(expired_rows),
            briefing_runs=len(briefing_rows),
            queued_projection_deletes=len(object_ids),
            conversation_images=len(expired_image_rows),
        )

    async def claim_deletions(
        self,
        *,
        now: datetime,
        limit: int = 500,
        lease_seconds: int = 300,
    ) -> tuple[ProjectionDeleteJob, ...]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit MUST be in [1, 5000]")
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds MUST be in [1, 3600]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT object_id, attempts FROM user_context_projection_delete_queue "
                "WHERE available_at <= %s AND (leased_until IS NULL OR leased_until <= %s) "
                "ORDER BY available_at, object_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (now, now, limit),
            )
            rows = await cursor.fetchall()
            lease_until = now + timedelta(seconds=lease_seconds)
            if rows:
                async with connection.cursor() as batch:
                    await batch.executemany(
                        "UPDATE user_context_projection_delete_queue SET leased_until = %s "
                        "WHERE object_id = %s",
                        [(lease_until, str(row["object_id"])) for row in rows],
                    )
        return tuple(
            ProjectionDeleteJob(str(row["object_id"]), int(row["attempts"])) for row in rows
        )

    async def complete_deletion(self, object_id: str) -> None:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM user_context_projection_delete_queue WHERE object_id = %s",
                (object_id,),
            )

    async def retry_deletion(
        self,
        object_id: str,
        *,
        available_at: datetime,
        error: str,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "UPDATE user_context_projection_delete_queue SET attempts = attempts + 1, "
                "available_at = %s, leased_until = NULL, last_error = %s "
                "WHERE object_id = %s",
                (available_at, error[:500], object_id),
            )

    async def _conversation_rows(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        before: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            "SELECT principal_id, conversation_id FROM conversation_record "
            "WHERE last_active < %s ORDER BY last_active, conversation_id "
            "FOR UPDATE SKIP LOCKED LIMIT %s",
            (before, limit),
        )
        return list(await cursor.fetchall())

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )


__all__ = [
    "PostgresUserContextRetention",
    "ProjectionDeleteJob",
    "UserContextRetentionReport",
]
