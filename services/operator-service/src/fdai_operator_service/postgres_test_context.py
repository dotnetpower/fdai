"""Context-command leases and principal-isolated status over Operator-owned outbox records."""

from __future__ import annotations

import json
from typing import Any

from fdai_service_contracts.test_context import TestContextApplication

from fdai_operator_service.postgres_family_store import PostgresFamilyStore


class PostgresTestContextOutbox:
    """Reuse the shared bounded PostgreSQL transport with context-specific statement ownership."""

    def __init__(self, store: PostgresFamilyStore) -> None:
        self._store = store

    async def claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Lease at most one pending or expired command without blocking other workers."""
        return await self._store._fetch_all(
            _CLAIM_SQL, {"claim_id": claim_id, "prefix": "operator-proposal:%"}
        )

    async def read_test_context_command(
        self, *, proposal_id: str, principal_id: str
    ) -> dict[str, object] | None:
        """Read the requesting human's delivery metadata, never request bodies or policy success."""
        rows = await self._store._fetch_all(
            "SELECT value->>'proposal_id' AS proposal_id, value->>'operation' AS operation, "
            "value->>'dispatch_status' AS dispatch_status, value->>'accepted_at' AS accepted_at, "
            "value->'context_application' AS context_application "
            "FROM state_kv WHERE key LIKE %(prefix)s AND value->>'family'='conversation' "
            "AND value->>'operation' IN "
            "('test-context.propose','test-context.review','test-context.revoke') "
            "AND value->>'proposal_id'=%(proposal_id)s "
            "AND value->>'principal_id'=%(principal_id)s LIMIT 1",
            {
                "prefix": "operator-proposal:%",
                "proposal_id": proposal_id,
                "principal_id": principal_id,
            },
        )
        return dict(rows[0]) if rows else None

    async def record_application(self, result: TestContextApplication) -> None:
        """Attach only an exact result to its original human command; conflicting replay fails."""
        from fdai_operator_service.test_context_runtime import command_from_record

        rows = await self._store._fetch_all(
            "SELECT key, value FROM state_kv WHERE key LIKE %(prefix)s "
            "AND value->>'family'='conversation' AND value->>'principal_id'=%(actor)s "
            "AND value->>'idempotency_key'=%(request_key)s "
            "AND value->>'operation' IN "
            "('test-context.propose','test-context.review','test-context.revoke') LIMIT 2",
            {
                "prefix": "operator-proposal:%",
                "actor": result.actor_id,
                "request_key": result.request_key,
            },
        )
        if not rows:
            raise LookupError("context application original command is unavailable")
        if len(rows) != 1 or not result.matches(command_from_record(rows[0]["value"])):
            raise ValueError("context application does not match the original command")
        payload = json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        updated = await self._store._fetch_all(
            "UPDATE state_kv SET value=value || jsonb_build_object("
            "'context_application',%(application)s::jsonb), updated_at=NOW() "
            "WHERE key=%(key)s AND value->>'request_digest'=%(request_digest)s "
            "AND (NOT value ? 'context_application' "
            "OR value->'context_application'=%(application)s::jsonb) "
            "RETURNING key",
            {
                "application": payload,
                "key": rows[0]["key"],
                "request_digest": rows[0]["value"]["request_digest"],
            },
        )
        if not updated:
            raise ValueError("context application conflicts with retained result")


_CLAIM_SQL = """
WITH candidate AS (
    SELECT key FROM state_kv
    WHERE key LIKE %(prefix)s AND value->>'family' = 'conversation'
      AND value->>'operation' IN (
          'test-context.propose','test-context.review','test-context.revoke')
      AND (value->>'dispatch_status' = 'pending' OR
          (value->>'dispatch_status' = 'claimed'
           AND (value->>'claim_expires_at')::timestamptz <= NOW()))
    ORDER BY COALESCE((value->>'attempt')::integer,0), value->>'accepted_at', key
    FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE state_kv AS proposal SET value = proposal.value || jsonb_build_object(
    'dispatch_status','claimed','claim_id',%(claim_id)s::text,
    'claim_worker_id','operator-test-context','claim_expires_at',NOW()+interval '30 seconds',
    'attempt',COALESCE((proposal.value->>'attempt')::integer,0)+1), updated_at=NOW()
FROM candidate WHERE proposal.key=candidate.key RETURNING proposal.key,proposal.value
"""
