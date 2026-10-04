"""Persist validated read-investigation completions in the Operator inbox."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

import psycopg
from fdai_service_contracts.read_investigation import ReadInvestigationCompletion
from psycopg.rows import dict_row

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelKind,
    channel_response_digest,
)
from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn

_COMPLETION_PREFIX: Final = "operator-read-investigation-completion:"
_EXTERNAL_COMPLETION_FRESHNESS: Final = timedelta(minutes=10)
_EXTERNAL_CHANNELS: Final = frozenset({ChannelKind.SLACK, ChannelKind.TEAMS})

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]


class ReadInvestigationCompletionRejectReason(StrEnum):
    """Typed fail-closed reasons for completion projection and outbound enqueue."""

    BINDING_AMBIGUOUS = "binding_ambiguous"
    BINDING_REVOKED = "binding_revoked"
    BINDING_UNVERIFIED = "binding_unverified"
    DELIVERY_CONFLICT = "delivery_conflict"
    DELIVERY_WINDOW_EXPIRED = "delivery_window_expired"
    NO_MATCHING_REQUEST = "no_matching_request"
    UNSUPPORTED_CHANNEL = "unsupported_channel"


class ReadInvestigationCompletionConflictError(RuntimeError):
    """A completion is unmatched or conflicts with immutable durable state."""

    def __init__(
        self,
        message: str,
        *,
        reason: ReadInvestigationCompletionRejectReason | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason


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

        channel_kind = _completion_channel_kind(completion)
        if channel_kind is not ChannelKind.WEB:
            return await self._project_external(completion, channel_kind=channel_kind)

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
                "read investigation completion has no matching durable request",
                reason=ReadInvestigationCompletionRejectReason.NO_MATCHING_REQUEST,
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
                "completion identity conflicts with immutable durable state",
                reason=ReadInvestigationCompletionRejectReason.DELIVERY_CONFLICT,
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

    async def _project_external(
        self,
        completion: ReadInvestigationCompletion,
        *,
        channel_kind: ChannelKind,
    ) -> StoredReadInvestigationCompletion:
        response = _outbound_response(completion)
        created_at = completion.completed_at
        expires_at = min(created_at + _EXTERNAL_COMPLETION_FRESHNESS, completion.retention_until)
        if expires_at <= created_at:
            raise ReadInvestigationCompletionConflictError(
                "completion retention closed before outbound enqueue",
                reason=ReadInvestigationCompletionRejectReason.DELIVERY_WINDOW_EXPIRED,
            )
        stream = f"read-investigation:{completion.origin.conversation_id}"
        event = "investigation.completed"
        delivery_key = _external_delivery_idempotency_key(completion)
        delivery_id = f"read-completion-delivery:{delivery_key[:40]}"
        response_json = json.dumps(response, separators=(",", ":"), sort_keys=True)
        record = _completion_record(completion)
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
                 LIMIT 1
            ),
            matching_bindings AS (
                SELECT binding_id, principal_id, scope_ref, conversation_id,
                       channel_kind, channel_id, state
                  FROM principal_conversation_binding
                  JOIN owned_request ON TRUE
                 WHERE principal_id = %(principal_id)s
                   AND channel_kind = %(channel_kind)s
                   AND channel_id = %(channel_id)s
                   AND conversation_id = %(conversation_id)s
            ),
            binding_counts AS (
                SELECT
                    COUNT(*) FILTER (WHERE state = 'active') AS active_count,
                    COUNT(*) FILTER (WHERE state = 'revoked') AS revoked_count
                  FROM matching_bindings
            ),
            selected_binding AS (
                SELECT binding_id, principal_id, scope_ref, conversation_id, channel_kind
                  FROM matching_bindings
                 WHERE state = 'active'
                   AND (SELECT active_count FROM binding_counts) = 1
                 LIMIT 1
            ),
            inserted_delivery AS (
                INSERT INTO conversation_outbound_delivery (
                    delivery_id, idempotency_key, principal_id, scope_ref, conversation_id,
                    binding_id, channel_kind, response, response_digest, state, created_at,
                    due_at, expires_at, retention_until, attempt_count, lease_owner,
                    lease_expires_at, last_error_code, duplicate_risk, terminal_at
                )
                SELECT %(delivery_id)s, %(delivery_idempotency_key)s,
                       principal_id, scope_ref, conversation_id, binding_id, channel_kind,
                       %(response)s::jsonb, %(response_digest)s, 'pending',
                       %(created_at)s, %(created_at)s, %(expires_at)s,
                       %(retention_until)s, 0, NULL, NULL, NULL, FALSE, NULL
                  FROM selected_binding
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING delivery_id, idempotency_key, principal_id, scope_ref,
                          conversation_id, binding_id, channel_kind, response_digest
            ),
            existing_delivery AS (
                SELECT existing.delivery_id, existing.idempotency_key, existing.principal_id,
                       existing.scope_ref, existing.conversation_id, existing.binding_id,
                       existing.channel_kind, existing.response_digest
                  FROM conversation_outbound_delivery AS existing
                  JOIN selected_binding AS binding ON TRUE
                 WHERE existing.idempotency_key = %(delivery_idempotency_key)s
                   AND existing.delivery_id = %(delivery_id)s
                   AND existing.principal_id = binding.principal_id
                   AND existing.scope_ref = binding.scope_ref
                   AND existing.conversation_id = binding.conversation_id
                   AND existing.binding_id = binding.binding_id
                   AND existing.channel_kind = binding.channel_kind
                   AND existing.response_digest = %(response_digest)s
                   AND NOT EXISTS (SELECT 1 FROM inserted_delivery)
                 LIMIT 1
            ),
            delivery_ready AS (
                SELECT TRUE AS inserted FROM inserted_delivery
                UNION ALL
                SELECT FALSE AS inserted FROM existing_delivery
            ),
            inserted AS (
                INSERT INTO operator_read_investigation_completion (
                    completion_id, task_id, principal_id, conversation_id, stream,
                    event, completion_digest, data, recorded_at, retention_until
                )
                SELECT %(completion_id)s, %(task_id)s, %(principal_id)s,
                       %(conversation_id)s, %(stream)s, %(event)s,
                       %(completion_digest)s, %(record)s::jsonb,
                       %(recorded_at)s, %(retention_until)s
                  FROM delivery_ready
                ON CONFLICT (completion_id) DO NOTHING
                RETURNING sequence, event, data
            ),
            existing_completion AS (
                SELECT existing.sequence, existing.event, existing.data
                  FROM operator_read_investigation_completion AS existing
                  JOIN owned_request ON TRUE
                 WHERE existing.completion_id = %(completion_id)s
            )
            SELECT sequence, event, data AS value, TRUE AS inserted,
                   NULL::text AS reject_reason
              FROM inserted
            UNION ALL
            SELECT existing.sequence, existing.event, existing.data AS value,
                   FALSE AS inserted, NULL::text AS reject_reason
              FROM existing_completion AS existing
             WHERE NOT EXISTS (SELECT 1 FROM inserted)
            UNION ALL
            SELECT 0 AS sequence, '' AS event,
                   jsonb_build_object('reject_reason', 'delivery_conflict') AS value,
                   FALSE AS inserted, 'delivery_conflict' AS reject_reason
             WHERE EXISTS (SELECT 1 FROM selected_binding)
               AND NOT EXISTS (SELECT 1 FROM delivery_ready)
               AND NOT EXISTS (SELECT 1 FROM inserted)
               AND NOT EXISTS (SELECT 1 FROM existing_completion)
            UNION ALL
            SELECT 0 AS sequence, '' AS event,
                   jsonb_build_object(
                       'reject_reason',
                       CASE
                           WHEN NOT EXISTS (SELECT 1 FROM owned_request)
                           THEN 'no_matching_request'
                           WHEN (SELECT active_count FROM binding_counts) > 1
                           THEN 'binding_ambiguous'
                           WHEN (SELECT revoked_count FROM binding_counts) > 0
                           THEN 'binding_revoked'
                           ELSE 'binding_unverified'
                       END
                   ) AS value,
                   FALSE AS inserted,
                   CASE
                       WHEN NOT EXISTS (SELECT 1 FROM owned_request)
                       THEN 'no_matching_request'
                       WHEN (SELECT active_count FROM binding_counts) > 1
                       THEN 'binding_ambiguous'
                       WHEN (SELECT revoked_count FROM binding_counts) > 0
                       THEN 'binding_revoked'
                       ELSE 'binding_unverified'
                   END AS reject_reason
             WHERE NOT EXISTS (SELECT 1 FROM selected_binding)
               AND NOT EXISTS (SELECT 1 FROM inserted)
               AND NOT EXISTS (SELECT 1 FROM existing_completion)
            LIMIT 1
            """,
            {
                "request_key": _request_key(completion.request_idempotency_key),
                "record": json.dumps(record, separators=(",", ":"), sort_keys=True),
                "principal_id": completion.owner_principal_id,
                "request_idempotency_key": completion.request_idempotency_key,
                "conversation_id": completion.origin.conversation_id,
                "correlation_id": completion.correlation_id,
                "channel_kind": channel_kind.value,
                "channel_id": completion.origin.channel_id,
                "delivery_id": delivery_id,
                "delivery_idempotency_key": delivery_key,
                "response": response_json,
                "response_digest": channel_response_digest(response),
                "created_at": created_at,
                "expires_at": expires_at,
                "retention_until": completion.retention_until,
                "completion_id": completion.completion_id,
                "task_id": completion.task_id,
                "stream": stream,
                "event": event,
                "completion_digest": completion.completion_digest,
                "recorded_at": completion.completed_at,
            },
        )
        if not rows:
            raise ReadInvestigationCompletionConflictError(
                "read investigation completion has no matching durable request",
                reason=ReadInvestigationCompletionRejectReason.NO_MATCHING_REQUEST,
            )
        row = rows[0]
        reject_reason = row.get("reject_reason")
        if reject_reason is not None:
            reason = ReadInvestigationCompletionRejectReason(str(reject_reason))
            raise ReadInvestigationCompletionConflictError(
                f"completion outbound enqueue rejected: {reason.value}",
                reason=reason,
            )
        stored = _object(row.get("value"))
        sequence = row.get("sequence")
        stored_event = row.get("event")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or stored_event != event
            or stored.get("stream") != stream
            or stored.get("event") != event
            or stored.get("completion_digest") != completion.completion_digest
            or stored.get("completion_id") != completion.completion_id
            or stored.get("task_id") != completion.task_id
            or stored.get("principal_id") != completion.owner_principal_id
        ):
            raise ReadInvestigationCompletionConflictError(
                "completion identity conflicts with immutable durable state",
                reason=ReadInvestigationCompletionRejectReason.DELIVERY_CONFLICT,
            )
        return StoredReadInvestigationCompletion(
            completion_id=completion.completion_id,
            task_id=completion.task_id,
            principal_id=completion.owner_principal_id,
            sequence=sequence,
            event=event,
            data=stored,
            duplicate=row.get("inserted") is not True,
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
                normalize_psycopg_dsn(config.dsn),
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
                "completion conflicts with immutable Operator conversation state",
                reason=ReadInvestigationCompletionRejectReason.DELIVERY_CONFLICT,
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


def _completion_channel_kind(completion: ReadInvestigationCompletion) -> ChannelKind:
    try:
        channel_kind = ChannelKind(completion.origin.channel_kind)
    except ValueError as exc:
        raise ReadInvestigationCompletionConflictError(
            "read investigation completion origin channel is unsupported",
            reason=ReadInvestigationCompletionRejectReason.UNSUPPORTED_CHANNEL,
        ) from exc
    if channel_kind is ChannelKind.WEB:
        if completion.origin.channel_id != completion.owner_principal_id:
            raise ReadInvestigationCompletionConflictError(
                "web completion origin must remain principal-scoped",
                reason=ReadInvestigationCompletionRejectReason.NO_MATCHING_REQUEST,
            )
        return channel_kind
    if channel_kind not in _EXTERNAL_CHANNELS:
        raise ReadInvestigationCompletionConflictError(
            "read investigation completion origin channel is unsupported",
            reason=ReadInvestigationCompletionRejectReason.UNSUPPORTED_CHANNEL,
        )
    return channel_kind


def _completion_record(completion: ReadInvestigationCompletion) -> dict[str, object]:
    return {
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
        "stream": f"read-investigation:{completion.origin.conversation_id}",
        "event": "investigation.completed",
        "data": completion.model_dump(mode="json"),
    }


def _outbound_response(completion: ReadInvestigationCompletion) -> JsonObject:
    return {
        "status": "answered" if completion.status == "succeeded" else completion.status,
        "answer": _turn_content(completion),
        "verification": {
            "authority": "read-investigation-completion",
            "completion_id": completion.completion_id,
            "completion_digest": completion.completion_digest,
            "evidence_refs": list(completion.evidence_refs),
            "terminal_reason": completion.terminal_reason,
        },
        "read_investigation": {
            "task_id": completion.task_id,
            "attempt_id": completion.attempt_id,
            "attempt_number": completion.attempt_number,
            "correlation_id": completion.correlation_id,
            "status": completion.status,
        },
        "trusted": False,
        "execution_authority": False,
    }


def _external_delivery_idempotency_key(completion: ReadInvestigationCompletion) -> str:
    raw = "\0".join(
        (
            "read-investigation-completion",
            completion.completion_id,
            completion.owner_principal_id,
            completion.origin.conversation_id,
            completion.origin.channel_kind,
            completion.origin.channel_id,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    "ReadInvestigationCompletionRejectReason",
    "ReadInvestigationCompletionStoreError",
    "StoredReadInvestigationCompletion",
    "completion_key",
]
