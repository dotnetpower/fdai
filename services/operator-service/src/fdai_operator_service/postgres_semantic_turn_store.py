"""Transactional PostgreSQL repository for Operator semantic turns."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from fdai_service_contracts import RuleSearchProjection, SemanticTurnRequest

_OUTBOX_PREFIX: Final = "operator-semantic-outbox:"
_RESULT_PREFIX: Final = "operator-semantic-result:"
_RULE_SEARCH_PROJECTION_PREFIX: Final = "operator-projection:workflow:rule.search:"

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]
InsertIfAbsent = Callable[..., Awaitable[tuple[bool, dict[str, object]]]]


class SemanticTurnConflictError(RuntimeError):
    """A semantic-turn identity is already bound to different durable content."""


class SemanticTurnStoreError(RuntimeError):
    """Durable semantic-turn state is unavailable or malformed."""


@dataclass(frozen=True, slots=True)
class StoredSemanticTurn:
    """One durable semantic request accepted into the Operator-owned outbox."""

    key: str
    proposal_id: str
    request_id: str
    principal_id: str
    envelope: Mapping[str, object]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class SemanticTurnClaim:
    """One atomically leased semantic request ready for transport publication."""

    key: str
    claim_id: str
    request_id: str
    principal_id: str
    envelope: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class StoredSemanticResult:
    """One idempotent principal-scoped terminal semantic projection."""

    sequence: int
    event: str
    request_id: str
    principal_id: str
    projection_id: str
    data: Mapping[str, object]
    duplicate: bool


class PostgresSemanticTurnRepository:
    """Persist semantic outbox and result records through injected transaction primitives."""

    def __init__(self, *, fetch_all: FetchAll, insert_if_absent: InsertIfAbsent) -> None:
        self._fetch_all = fetch_all
        self._insert_if_absent = insert_if_absent

    async def append(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
    ) -> StoredSemanticTurn:
        """Persist one v1.2 semantic request without publishing it in the transaction."""
        _bounded_component("principal_id", principal_id)
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str):
            raise ValueError("semantic envelope request_id MUST be a string")
        _bounded_component("request_id", request_id)
        requested_at = envelope.get("requested_at")
        semantic_turn = envelope.get("semantic_turn")
        if not isinstance(requested_at, str) or not isinstance(semantic_turn, Mapping):
            raise ValueError("semantic envelope structure is malformed")
        try:
            request = SemanticTurnRequest.model_validate(semantic_turn)
        except ValueError:
            raise ValueError("semantic envelope structure is malformed") from None
        if request.principal.subject_id != principal_id:
            raise ValueError("semantic envelope principal MUST match the durable owner")
        key = _outbox_key(idempotency_key)
        record: dict[str, object] = {
            "kind": "operator.semantic_turn",
            "proposal_id": f"semantic-{request_id}",
            "request_id": request_id,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "state": "pending",
            "attempt": 0,
            "accepted_at": requested_at,
            "envelope": dict(envelope),
        }
        inserted, stored = await self._insert_if_absent(key=key, value=record)
        if (
            stored.get("request_digest") != request_digest
            or stored.get("principal_id") != principal_id
            or stored.get("request_id") != request_id
        ):
            raise SemanticTurnConflictError(
                "idempotency key conflicts with a different semantic turn"
            )
        return _stored_turn(key, stored, duplicate=not inserted)

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        test_now: datetime | None = None,
    ) -> SemanticTurnClaim | None:
        """Lease one eligible turn using the database clock unless a test clock is explicit."""
        _bounded_component("worker_id", worker_id)
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        parameters: dict[str, object] = {
            "prefix": f"{_OUTBOX_PREFIX}%",
            "claim_id": claim_id,
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "test_now": _aware_utc(test_now) if test_now is not None else None,
        }
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                 WHERE key LIKE %(prefix)s
                   AND value ->> 'kind' = 'operator.semantic_turn'
                   AND (
                        value ->> 'state' = 'pending'
                        OR (
                            value ->> 'state' = 'claimed'
                            AND (value ->> 'lease_until')::timestamptz
                                <= COALESCE(%(test_now)s::timestamptz, NOW())
                        )
                   )
                 ORDER BY value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS target
               SET value = target.value || jsonb_build_object(
                       'state', 'claimed',
                       'claim_id', %(claim_id)s::text,
                       'lease_owner', %(worker_id)s::text,
                       'lease_until',
                           COALESCE(%(test_now)s::timestamptz, NOW())
                               + make_interval(secs => %(lease_seconds)s),
                       'attempt', COALESCE((target.value ->> 'attempt')::integer, 0) + 1
                   ),
                   updated_at = NOW()
              FROM candidate
             WHERE target.key = candidate.key
             RETURNING target.key, target.value
            """,
            parameters,
        )
        if not rows:
            return None
        key = rows[0].get("key")
        if not isinstance(key, str):
            raise SemanticTurnStoreError("semantic claim key is malformed")
        record = _json_object(rows[0].get("value"), label=key)
        turn = _stored_turn(key, record, duplicate=False)
        attempt = record.get("attempt")
        if not isinstance(attempt, int):
            raise SemanticTurnStoreError("semantic claim attempt is malformed")
        return SemanticTurnClaim(
            key=key,
            claim_id=claim_id,
            request_id=turn.request_id,
            principal_id=turn.principal_id,
            envelope=turn.envelope,
            attempt=attempt,
        )

    async def mark_published(self, *, key: str, claim_id: str) -> bool:
        """Compare-and-set one active claim to published after transport acceptance."""
        return await self._transition_claim(key=key, claim_id=claim_id, state="published")

    async def release_claim(self, *, key: str, claim_id: str) -> bool:
        """Compare-and-set one failed claim back to pending for bounded retry."""
        return await self._transition_claim(key=key, claim_id=claim_id, state="pending")

    async def read(
        self,
        *,
        principal_id: str,
        proposal_id: str,
    ) -> StoredSemanticTurn | None:
        """Read an accepted semantic turn only for its authenticated principal."""
        _bounded_component("principal_id", principal_id)
        _bounded_component("proposal_id", proposal_id)
        rows = await self._fetch_all(
            """
            SELECT key, value
              FROM state_kv
             WHERE key LIKE %(prefix)s
               AND value ->> 'principal_id' = %(principal_id)s
               AND value ->> 'proposal_id' = %(proposal_id)s
             LIMIT 1
            """,
            {
                "prefix": f"{_OUTBOX_PREFIX}%",
                "principal_id": principal_id,
                "proposal_id": proposal_id,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        if not isinstance(key, str):
            raise SemanticTurnStoreError("semantic outbox key is malformed")
        return _stored_turn(
            key,
            _json_object(rows[0].get("value"), label=key),
            duplicate=True,
        )

    async def project(self, *, projection: Mapping[str, object]) -> StoredSemanticResult:
        """Idempotently project a validated result against its owning durable request."""
        projection_id = projection.get("projection_id")
        request_id = projection.get("request_id")
        recorded_at = projection.get("recorded_at")
        semantic_result = projection.get("semantic_result")
        if not isinstance(projection_id, str) or not isinstance(request_id, str):
            raise ValueError("semantic projection identities MUST be strings")
        if not isinstance(recorded_at, str) or not isinstance(semantic_result, dict):
            raise ValueError("semantic projection terminal fields are malformed")
        turn_sequence = semantic_result.get("turn_sequence")
        session_id = semantic_result.get("session_id")
        turn_id = semantic_result.get("turn_id")
        if (
            not isinstance(turn_sequence, int)
            or not isinstance(session_id, str)
            or not isinstance(turn_id, str)
        ):
            raise ValueError("semantic result turn identity is malformed")
        payload = projection.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("semantic projection payload MUST be an object")
        rule_search_value = payload.get("rule_search")
        rule_search = (
            None
            if rule_search_value is None
            else RuleSearchProjection.model_validate(rule_search_value)
        )
        if rule_search is not None and semantic_result.get("disposition") != "answered":
            raise ValueError("Rule search projection requires an answered semantic result")
        projection_digest = _digest(dict(projection))
        key = _result_key(request_id, projection_id)
        record = {
            "kind": "operator.semantic_result",
            "projection_id": projection_id,
            "request_id": request_id,
            "projection_digest": projection_digest,
            "event": "semantic_turn_result",
            "event_sequence": turn_sequence + 1,
            "recorded_at": recorded_at,
            "data": dict(projection),
        }
        rows = await self._project_rows(
            request_id=request_id,
            session_id=session_id,
            turn_id=turn_id,
            turn_sequence=turn_sequence,
            result_key=key,
            projection_digest=projection_digest,
            record=record,
            recorded_at=recorded_at,
            rule_projection_record=(
                None
                if rule_search is None
                else {
                    "kind": "operator.workflow_rule_search_projection",
                    "projection_id": projection_id,
                    "request_id": request_id,
                    "query_digest": rule_search.query_digest,
                    "retrieval_receipt_digest": rule_search.retrieval_receipt_digest,
                    "catalog_digest": rule_search.retrieval_receipt.catalog_digest,
                    "generation_digest": rule_search.retrieval_receipt.generation_digest,
                    "recorded_at": recorded_at,
                    "_revision": projection_id,
                    "data": rule_search.model_dump(mode="json"),
                }
            ),
        )
        if not rows:
            raise SemanticTurnConflictError("semantic result has no matching durable request")
        stored = _json_object(rows[0].get("value"), label=key)
        if stored.get("projection_digest") != projection_digest:
            raise SemanticTurnConflictError(
                "projection id conflicts with a different semantic result"
            )
        result = _stored_result(stored, duplicate=rows[0].get("inserted") is not True)
        if result.request_id != request_id or result.projection_id != projection_id:
            raise SemanticTurnConflictError(
                "semantic result identity conflicts with the durable request"
            )
        return result

    async def replay(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]:
        """Replay ordered terminal events isolated by authenticated principal and request."""
        _bounded_component("principal_id", principal_id)
        _bounded_component("request_id", request_id)
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence MUST be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("replay limit MUST be in [1, 500]")
        rows = await self._fetch_all(
            """
            SELECT value
              FROM state_kv
             WHERE key LIKE %(prefix)s
               AND value ->> 'principal_id' = %(principal_id)s
               AND value ->> 'request_id' = %(request_id)s
               AND (value ->> 'event_sequence')::bigint > %(after_sequence)s
             ORDER BY (value ->> 'event_sequence')::bigint,
                                            (value ->> 'recorded_at')::timestamptz,
                      value ->> 'projection_id'
             LIMIT %(limit)s
            """,
            {
                "prefix": f"{_RESULT_PREFIX}%",
                "principal_id": principal_id,
                "request_id": request_id,
                "after_sequence": after_sequence or 0,
                "limit": limit,
            },
        )
        return tuple(
            _stored_result(
                _json_object(row.get("value"), label="semantic result"),
                duplicate=True,
            )
            for row in rows
        )

    async def _transition_claim(self, *, key: str, claim_id: str, state: str) -> bool:
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = value || jsonb_build_object(
                       'state', %(state)s::text,
                       'claim_id', NULL,
                       'lease_owner', NULL,
                       'lease_until', NULL
                   ),
                   updated_at = NOW()
             WHERE key = %(key)s
               AND value ->> 'state' = 'claimed'
               AND value ->> 'claim_id' = %(claim_id)s
            RETURNING value
            """,
            {"state": state, "key": key, "claim_id": claim_id},
        )
        return bool(rows)

    async def _project_rows(
        self,
        *,
        request_id: str,
        session_id: str,
        turn_id: str,
        turn_sequence: int,
        result_key: str,
        projection_digest: str,
        record: Mapping[str, object],
        recorded_at: str,
        rule_projection_record: Mapping[str, object] | None,
    ) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """
            WITH owned_request AS (
                SELECT key, value ->> 'principal_id' AS principal_id
                  FROM state_kv
                 WHERE key LIKE %(outbox_prefix)s
                   AND value ->> 'request_id' = %(request_id)s
                   AND value #>> '{envelope,semantic_turn,session_id}' = %(session_id)s
                   AND value #>> '{envelope,semantic_turn,turn_id}' = %(turn_id)s
                   AND (value #>> '{envelope,semantic_turn,turn_sequence}')::bigint
                       = %(turn_sequence)s
                 LIMIT 1
                 FOR UPDATE
            ), rule_target AS (
                SELECT %(rule_projection_prefix)s
                           || encode(
                               sha256(
                                   convert_to(
                                       owned_request.principal_id
                                       || chr(31)
                                       || %(rule_query_digest)s,
                                       'UTF8'
                                   )
                               ),
                               'hex'
                           ) AS key,
                       owned_request.principal_id,
                       %(rule_query_digest)s::text AS query_digest
                  FROM owned_request
                      WHERE %(rule_projection_record)s::jsonb IS NOT NULL
            ), rule_identity_conflict AS (
                SELECT TRUE
                  FROM state_kv AS target
                  JOIN rule_target ON rule_target.key = target.key
                      WHERE target.value ->> 'principal_id'
                                    IS DISTINCT FROM rule_target.principal_id
                          OR target.value ->> 'query_digest'
                                    IS DISTINCT FROM rule_target.query_digest
                 FOR UPDATE OF target
            ), existing AS (
                SELECT existing.value
                  FROM state_kv AS existing
                  CROSS JOIN owned_request
                 WHERE existing.key = %(result_key)s
                   AND existing.value ->> 'request_id' = %(request_id)s
                   AND existing.value ->> 'projection_id' = %(projection_id)s
                   AND existing.value ->> 'principal_id'
                       = owned_request.principal_id
                   AND existing.value ->> 'projection_digest'
                       = %(projection_digest)s
                 FOR UPDATE OF existing
            ), inserted AS (
                INSERT INTO state_kv (key, value)
                SELECT %(result_key)s,
                       %(record)s::jsonb || jsonb_build_object(
                           'principal_id', owned_request.principal_id
                       )
                  FROM owned_request
                                 WHERE NOT EXISTS (SELECT 1 FROM rule_identity_conflict)
                ON CONFLICT (key) DO NOTHING
                RETURNING value
            ), accepted AS (
                                SELECT TRUE AS inserted, value
                                    FROM inserted
                                 WHERE NOT EXISTS (SELECT 1 FROM rule_identity_conflict)
                UNION ALL
                                SELECT FALSE AS inserted, value
                                    FROM existing
                                 WHERE NOT EXISTS (SELECT 1 FROM rule_identity_conflict)
            ), completed AS (
                UPDATE state_kv AS target
                   SET value = target.value || jsonb_build_object(
                           'state', 'completed',
                       'completed_at', %(recorded_at)s::text
                       ),
                       updated_at = NOW()
                  FROM owned_request
                 WHERE target.key = owned_request.key
                   AND EXISTS (SELECT 1 FROM accepted)
                RETURNING target.key
            ), rule_projected AS (
                INSERT INTO state_kv AS target (key, value)
                SELECT rule_target.key,
                       %(rule_projection_record)s::jsonb || jsonb_build_object(
                           'principal_id', rule_target.principal_id
                       )
                  FROM accepted
                  CROSS JOIN rule_target
                ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value,
                       updated_at = NOW()
                 WHERE target.value ->> 'principal_id'
                           = EXCLUDED.value ->> 'principal_id'
                   AND target.value ->> 'query_digest'
                           = EXCLUDED.value ->> 'query_digest'
                   AND (target.value ->> 'recorded_at')::timestamptz
                           <= (EXCLUDED.value ->> 'recorded_at')::timestamptz
                   AND (
                       (target.value ->> 'recorded_at')::timestamptz
                           < (EXCLUDED.value ->> 'recorded_at')::timestamptz
                       OR (target.value ->> 'projection_id')
                           < (EXCLUDED.value ->> 'projection_id')
                   )
                RETURNING key
            )
            SELECT inserted,
                   value,
                   (SELECT count(*) FROM rule_projected) AS rule_projection_writes
              FROM accepted
            """,
            {
                "outbox_prefix": f"{_OUTBOX_PREFIX}%",
                "request_id": request_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "turn_sequence": turn_sequence,
                "result_key": result_key,
                "projection_id": record["projection_id"],
                "projection_digest": projection_digest,
                "record": json.dumps(dict(record), separators=(",", ":"), sort_keys=True),
                "recorded_at": recorded_at,
                "rule_projection_prefix": _RULE_SEARCH_PROJECTION_PREFIX,
                "rule_query_digest": (
                    None
                    if rule_projection_record is None
                    else rule_projection_record["query_digest"]
                ),
                "rule_projection_record": (
                    None
                    if rule_projection_record is None
                    else json.dumps(
                        dict(rule_projection_record),
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                ),
            },
        )


def rule_search_projection_key(principal_id: str, query_digest: str) -> str:
    """Return the principal/query-isolated key used by the Rule-search materializer."""

    _bounded_component("principal_id", principal_id)
    _bounded_component("query_digest", query_digest)
    identity = f"{principal_id}\x1f{query_digest}".encode()
    digest = hashlib.sha256(identity).hexdigest()
    return f"{_RULE_SEARCH_PROJECTION_PREFIX}{digest}"


def _outbox_key(idempotency_key: str) -> str:
    if not idempotency_key.strip() or len(idempotency_key) > 256:
        raise ValueError("idempotency_key MUST be a bounded non-empty string")
    return f"{_OUTBOX_PREFIX}{hashlib.sha256(idempotency_key.encode()).hexdigest()}"


def _result_key(request_id: str, projection_id: str) -> str:
    _bounded_component("request_id", request_id)
    _bounded_component("projection_id", projection_id)
    identity = f"{request_id}\0{projection_id}".encode()
    return f"{_RESULT_PREFIX}{hashlib.sha256(identity).hexdigest()}"


def _bounded_component(name: str, value: str) -> None:
    if not value.strip() or len(value) > 128:
        raise ValueError(f"{name} MUST be a bounded non-empty string")


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SemanticTurnStoreError(f"{label} is not a JSON object")
    return {str(key): item for key, item in value.items()}


def _stored_turn(
    key: str,
    record: Mapping[str, object],
    *,
    duplicate: bool,
) -> StoredSemanticTurn:
    proposal_id = record.get("proposal_id")
    request_id = record.get("request_id")
    principal_id = record.get("principal_id")
    envelope = record.get("envelope")
    if not all(isinstance(value, str) for value in (proposal_id, request_id, principal_id)):
        raise SemanticTurnStoreError("stored semantic turn identity is malformed")
    if not isinstance(envelope, dict):
        raise SemanticTurnStoreError("stored semantic turn envelope is malformed")
    return StoredSemanticTurn(
        key=key,
        proposal_id=str(proposal_id),
        request_id=str(request_id),
        principal_id=str(principal_id),
        envelope=_json_object(envelope, label=f"{key}.envelope"),
        duplicate=duplicate,
    )


def _stored_result(
    record: Mapping[str, object],
    *,
    duplicate: bool,
) -> StoredSemanticResult:
    sequence = record.get("event_sequence")
    event = record.get("event")
    request_id = record.get("request_id")
    principal_id = record.get("principal_id")
    projection_id = record.get("projection_id")
    data = record.get("data")
    if not isinstance(sequence, int) or not all(
        isinstance(value, str) for value in (event, request_id, principal_id, projection_id)
    ):
        raise SemanticTurnStoreError("stored semantic result identity is malformed")
    if not isinstance(data, dict):
        raise SemanticTurnStoreError("stored semantic result data is malformed")
    return StoredSemanticResult(
        sequence=sequence,
        event=str(event),
        request_id=str(request_id),
        principal_id=str(principal_id),
        projection_id=str(projection_id),
        data=_json_object(data, label=f"semantic result {projection_id}"),
        duplicate=duplicate,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("semantic lease time MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "PostgresSemanticTurnRepository",
    "SemanticTurnClaim",
    "SemanticTurnConflictError",
    "SemanticTurnStoreError",
    "StoredSemanticResult",
    "StoredSemanticTurn",
]
