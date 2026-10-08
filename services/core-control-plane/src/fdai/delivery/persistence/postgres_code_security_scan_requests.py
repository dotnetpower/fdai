"""Claim and close Console code-security scan requests in the Operator proposal outbox.

The Operator API persists each request as a pending ``operator-proposal:operations:*`` row with
operation ``code_security.scan_request``. This queue leases one row at a time with ``SKIP
LOCKED``, so concurrent workers never scan the same request, and an expired lease is claimed
again with a higher attempt count. Closing a claim requires the matching claim id.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.code_security_scan_requests import (
    SCAN_REQUEST_OPERATION,
    ClaimedScanRequest,
    parse_scan_request,
)


@dataclass(frozen=True, slots=True)
class PostgresCodeSecurityScanRequestQueueConfig:
    dsn: str = ""
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    worker_id: str = "core-code-security-scan"
    lease_seconds: int = 3_600


class PostgresCodeSecurityScanRequestQueue:
    """Lease pending scan requests without executing anything in the Operator route."""

    def __init__(self, config: PostgresCodeSecurityScanRequestQueueConfig) -> None:
        if not config.dsn.strip():
            raise ValueError("code-security scan request queue dsn MUST be non-empty")
        if not 60 <= config.lease_seconds <= 7_200:
            raise ValueError("lease_seconds MUST be in [60, 7200]")
        self._config = config

    async def claim(self) -> ClaimedScanRequest | None:
        claim_id = str(uuid4())
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                 WHERE key LIKE %(prefix)s
                   AND value ->> 'family' = 'operations'
                   AND value ->> 'operation' = %(operation)s
                   AND (
                        value ->> 'dispatch_status' = 'pending'
                        OR (
                            value ->> 'dispatch_status' = 'claimed'
                            AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                        )
                   )
                 ORDER BY value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                   'dispatch_status', 'claimed',
                   'claim_id', %(claim_id)s::text,
                   'claim_worker_id', %(worker_id)s::text,
                   'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
                   'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
               ),
                   updated_at = NOW()
              FROM candidate
             WHERE proposal.key = candidate.key
         RETURNING proposal.key, proposal.value
            """,
            {
                "prefix": "operator-proposal:operations:%",
                "operation": SCAN_REQUEST_OPERATION,
                "claim_id": claim_id,
                "worker_id": self._config.worker_id,
                "lease_seconds": self._config.lease_seconds,
            },
        )
        if not rows:
            return None
        key, record = rows[0].get("key"), rows[0].get("value")
        if not isinstance(key, str) or not isinstance(record, Mapping):
            raise ValueError("code-security scan request claim is malformed")
        attempt = record.get("attempt")
        return ClaimedScanRequest(
            key=key,
            claim_id=str(record.get("claim_id") or claim_id),
            request=parse_scan_request(record),
            attempt=attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else 1,
        )

    async def mark_completed(
        self, *, key: str, claim_id: str, result: Mapping[str, object]
    ) -> bool:
        return await self._mark(
            key=key,
            claim_id=claim_id,
            update={"dispatch_status": "published", "scan_result": dict(result)},
        )

    async def mark_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool:
        return await self._mark(
            key=key,
            claim_id=claim_id,
            update={"dispatch_status": "rejected", "rejection_reason": reason_code},
        )

    async def _mark(self, *, key: str, claim_id: str, update: Mapping[str, object]) -> bool:
        closed = {**dict(update), "closed_at": datetime.now(UTC).isoformat()}
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = value || %(update)s::jsonb, updated_at = NOW()
             WHERE key = %(key)s
               AND value ->> 'claim_id' = %(claim_id)s
               AND value ->> 'dispatch_status' = 'claimed'
         RETURNING key
            """,
            {"key": key, "claim_id": claim_id, "update": json.dumps(closed)},
        )
        return bool(rows)

    async def _fetch_all(
        self, query: str, parameters: Mapping[str, object] | None = None
    ) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(query, parameters or {})
            return list(await cursor.fetchall())


__all__ = [
    "PostgresCodeSecurityScanRequestQueue",
    "PostgresCodeSecurityScanRequestQueueConfig",
]
