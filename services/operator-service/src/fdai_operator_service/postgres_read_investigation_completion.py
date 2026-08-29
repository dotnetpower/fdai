"""Persist validated read-investigation completions in the Operator inbox."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from fdai_service_contracts.read_investigation import ReadInvestigationCompletion
from psycopg.rows import dict_row

_COMPLETION_PREFIX: Final = "operator-read-investigation-completion:"

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]


class ReadInvestigationCompletionConflictError(RuntimeError):
    """A completion is unmatched or conflicts with immutable durable state."""


class ReadInvestigationCompletionStoreError(RuntimeError):
    """Durable completion state is unavailable or malformed."""


@dataclass(frozen=True, slots=True)
class StoredReadInvestigationCompletion:
    """One principal-scoped terminal completion accepted by the Operator."""

    completion_id: str
    task_id: str
    principal_id: str
    sequence: int
    event: str
    data: Mapping[str, object]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class PostgresReadInvestigationCompletionConfig:
    """Configure bounded Operator completion inbox connections."""

    dsn: str
    statement_timeout_ms: int = 20_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("completion inbox dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("completion inbox timeouts MUST be positive")


class PostgresReadInvestigationCompletionRepository:
    """Project immutable completions only against their durable request owner."""

    def __init__(
        self,
        *,
        fetch_all: FetchAll | None = None,
        config: PostgresReadInvestigationCompletionConfig | None = None,
    ) -> None:
        if (fetch_all is None) == (config is None):
            raise ValueError("completion repository requires exactly one PostgreSQL binding")
        self._injected_fetch_all = fetch_all
        self._config = config

    async def project_read_investigation_completion(
        self,
        completion: ReadInvestigationCompletion,
    ) -> StoredReadInvestigationCompletion:
        """Satisfy the completion consumer's Operator-owned store contract."""

        return await self.project(completion)

    async def project(
        self,
        completion: ReadInvestigationCompletion,
    ) -> StoredReadInvestigationCompletion:
        """Insert one completion or return its exact idempotent replay."""

        completion_data = completion.model_dump(mode="json")
        stream = f"read-investigation:{completion.origin.conversation_id}"
        event = "investigation.completed"
        turn_id = f"turn:{completion.completion_id}"
        turn_content = _turn_content(completion)
        turn_metadata = {
            "kind": "read-investigation-completion",
            "completion_id": completion.completion_id,
            "task_id": completion.task_id,
            "attempt_id": completion.attempt_id,
            "correlation_id": completion.correlation_id,
            "terminal_reason": completion.terminal_reason,
            "status": completion.status,
            "evidence_refs": list(completion.evidence_refs),
            "trusted": False,
        }
        record: dict[str, object] = {
            "kind": "operator.read_investigation_completion",
            "completion_id": completion.completion_id,
            "task_id": completion.task_id,
            "principal_id": completion.owner_principal_id,
            "request_idempotency_key": completion.request_idempotency_key,
            "correlation_id": completion.correlation_id,
            "conversation_id": completion.origin.conversation_id,
            "completion_digest": completion.completion_digest,
            "recorded_at": completion.completed_at.isoformat(),
            "retention_until": completion.retention_until.isoformat(),
            "stream": stream,
            "event": event,
            "turn_id": turn_id,
            "data": completion_data,
        }
        rows = await self._fetch_all(
            """
            WITH owned_request AS (
                SELECT key, value
                  FROM state_kv
                                 WHERE key = %(request_key)s
                                     AND value ->> 'kind' = 'operator.proposal'
                   AND value ->> 'family' = 'operations'
                   AND value ->> 'operation' = 'read_investigation.start'
                   AND value ->> 'principal_id' = %(principal_id)s
                   AND value ->> 'idempotency_key' = %(request_idempotency_key)s
                   AND value ->> 'proposal_id' = %(conversation_id)s
                   AND COALESCE(
                           value #>> '{payload,correlation_id}',
                           value ->> 'proposal_id'
                       ) = %(correlation_id)s
                   AND %(channel_kind)s = 'web'
                   AND %(channel_id)s = %(principal_id)s
                 LIMIT 1
            ),
                                                existing_turn AS (
                                                        SELECT turn_id
                                                            FROM conversation_turn
                                                         WHERE principal_id = %(principal_id)s
                                                             AND idempotency_key = %(completion_id)s
                                                             AND turn_id = %(turn_id)s
                                                             AND content = %(turn_content)s
                                                               AND metadata ->> 'completion_id'
                                                                   = %(completion_id)s
                                                         LIMIT 1
                                                ),
                        conversation_ready AS (
                                INSERT INTO conversation_record (
                                principal_id, conversation_id, channel_id,
                                started_at, last_active, status, next_turn_index
                                )
                                SELECT %(principal_id)s, %(conversation_id)s, %(channel_id)s,
                                             (value ->> 'accepted_at')::timestamptz,
                                             %(recorded_at)s, 'active', 1
                                    FROM owned_request
                                ON CONFLICT (principal_id, conversation_id) DO UPDATE
                                        SET last_active = GREATEST(
                                                conversation_record.last_active,
                                                EXCLUDED.last_active
                                        ),
                                            next_turn_index = CASE
                                                WHEN EXISTS (SELECT 1 FROM existing_turn)
                                                THEN conversation_record.next_turn_index
                                                ELSE conversation_record.next_turn_index + 1
                                            END
                                    WHERE conversation_record.channel_id = EXCLUDED.channel_id
                                RETURNING principal_id, conversation_id,
                                          next_turn_index - 1 AS turn_index
                            ),
                        turn_inserted AS (
                                INSERT INTO conversation_turn (
                                principal_id, conversation_id, turn_id,
                                turn_index, role, content,
                                        recorded_at, idempotency_key, metadata
                                )
                            SELECT principal_id, conversation_id,
                                     %(turn_id)s,
                                         turn_index, 'assistant',
                                         %(turn_content)s,
                                             %(recorded_at)s, %(completion_id)s,
                                             %(turn_metadata)s::jsonb
                                    FROM conversation_ready
                                   WHERE NOT EXISTS (SELECT 1 FROM existing_turn)
                                ON CONFLICT (principal_id, idempotency_key) DO NOTHING
                                RETURNING turn_id
                        ),
                        turn_ready AS (
                                SELECT turn_id FROM turn_inserted
                                UNION ALL
                                SELECT turn_id FROM existing_turn
                                 WHERE NOT EXISTS (SELECT 1 FROM turn_inserted)
                        ),
            inserted AS (
                                INSERT INTO operator_read_investigation_completion (
                            completion_id, task_id, principal_id,
                            conversation_id, stream,
                                        event, completion_digest, data, recorded_at, retention_until
                                )
                                SELECT %(completion_id)s, %(task_id)s, %(principal_id)s,
                                             %(conversation_id)s, %(stream)s, %(event)s,
                                             %(completion_digest)s, %(record)s::jsonb,
                                             %(recorded_at)s, %(retention_until)s
                                    FROM turn_ready
                                ON CONFLICT (completion_id) DO NOTHING
                                RETURNING sequence, event, data
            )
                        SELECT sequence, event, data AS value, TRUE AS inserted
              FROM inserted
            UNION ALL
                        SELECT existing.sequence, existing.event, existing.data AS value,
                                     FALSE AS inserted
                            FROM operator_read_investigation_completion AS existing
                            JOIN owned_request ON TRUE
                            JOIN turn_ready ON TRUE
                         WHERE existing.completion_id = %(completion_id)s
               AND NOT EXISTS (SELECT 1 FROM inserted)
             LIMIT 1
            """,
            {
                "request_key": _request_key(completion.request_idempotency_key),
                "record": json.dumps(record, separators=(",", ":"), sort_keys=True),
                "turn_metadata": json.dumps(
                    turn_metadata,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "principal_id": completion.owner_principal_id,
                "request_idempotency_key": completion.request_idempotency_key,
                "conversation_id": completion.origin.conversation_id,
                "correlation_id": completion.correlation_id,
                "channel_kind": completion.origin.channel_kind,
                "channel_id": completion.origin.channel_id,
                "completion_id": completion.completion_id,
                "completion_digest": completion.completion_digest,
                "task_id": completion.task_id,
                "stream": stream,
                "event": event,
                "turn_id": turn_id,
                "turn_content": turn_content,
                "recorded_at": completion.completed_at,
                "retention_until": completion.retention_until,
            },
        )
        if not rows:
            raise ReadInvestigationCompletionConflictError(
                "read investigation completion has no matching durable request"
            )
        stored = _object(rows[0].get("value"))
        sequence = rows[0].get("sequence")
        stored_event = rows[0].get("event")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or stored_event != event
            or stored.get("stream") != stream
            or stored.get("event") != event
            or stored.get("turn_id") != turn_id
            or stored.get("completion_digest") != completion.completion_digest
            or stored.get("completion_id") != completion.completion_id
            or stored.get("task_id") != completion.task_id
            or stored.get("principal_id") != completion.owner_principal_id
        ):
            raise ReadInvestigationCompletionConflictError(
                "completion identity conflicts with immutable durable state"
            )
        return StoredReadInvestigationCompletion(
            completion_id=completion.completion_id,
            task_id=completion.task_id,
            principal_id=completion.owner_principal_id,
            sequence=sequence,
            event=event,
            data=stored,
            duplicate=rows[0].get("inserted") is not True,
        )

    async def purge_expired_read_investigation_completions(
        self,
        *,
        now: datetime,
        limit: int = 200,
    ) -> int:
        """Delete a bounded batch only after each completion retention deadline."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("completion retention time MUST be timezone-aware")
        if not 1 <= limit <= 500:
            raise ValueError("completion retention limit MUST be between 1 and 500")
        rows = await self._fetch_all(
            """
            WITH expired AS (
                SELECT completion_id
                  FROM operator_read_investigation_completion
                 WHERE retention_until <= %(now)s
                 ORDER BY retention_until, sequence
                 FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
            )
            DELETE FROM operator_read_investigation_completion AS target
             USING expired
             WHERE target.completion_id = expired.completion_id
            RETURNING target.completion_id
            """,
            {"now": now, "limit": limit},
        )
        return len(rows)

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        try:
            if self._injected_fetch_all is not None:
                return await self._injected_fetch_all(statement, parameters)
            config = self._config
            if config is None:  # pragma: no cover - constructor invariant
                raise RuntimeError("completion repository PostgreSQL binding is unavailable")
            async with await psycopg.AsyncConnection.connect(
                config.dsn,
                row_factory=dict_row,
                connect_timeout=config.connect_timeout_s,
                autocommit=True,
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, false)",
                    (str(config.statement_timeout_ms),),
                )
                cursor = await connection.execute(statement, parameters)
                return list(await cursor.fetchall())
        except psycopg.IntegrityError as exc:
            raise ReadInvestigationCompletionConflictError(
                "completion conflicts with immutable Operator conversation state"
            ) from exc
        except psycopg.Error as exc:
            raise ReadInvestigationCompletionStoreError(
                "Operator completion inbox is unavailable"
            ) from exc


def completion_key(completion_id: str) -> str:
    """Return the stable Operator inbox key for one terminal completion."""

    return f"{_COMPLETION_PREFIX}{completion_id}"


def _request_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"operator-proposal:operations:{digest}"


def _turn_content(completion: ReadInvestigationCompletion) -> str:
    label = f"[Background task result: {completion.terminal_reason}]"
    summary = (completion.summary or "").strip()
    return f"{label}\n{summary}" if summary else label


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReadInvestigationCompletionStoreError(
            "stored read investigation completion is malformed"
        )
    return dict(value)


__all__ = [
    "PostgresReadInvestigationCompletionConfig",
    "PostgresReadInvestigationCompletionRepository",
    "ReadInvestigationCompletionConflictError",
    "ReadInvestigationCompletionStoreError",
    "StoredReadInvestigationCompletion",
    "completion_key",
]
