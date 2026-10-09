"""Claim and close Console code-security requests in the Operator proposal outbox.

The Operator API persists each request as a pending ``operator-proposal:operations:*`` row with
operation ``code_security.repository_change`` or ``code_security.scan_request``. This queue
leases one row at a time with ``SKIP LOCKED``, oldest first, so concurrent workers never process
the same request and a registration accepted earlier is applied before a later scan. An expired
lease is claimed again with a higher attempt count. Closing a claim requires the matching id.
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

from fdai.delivery.code_security_repository_changes import (
    REPOSITORY_CHANGE_OPERATION,
    parse_repository_change,
)
from fdai.delivery.code_security_scan_requests import (
    SCAN_REQUEST_OPERATION,
    ClaimedScanRequest,
    parse_scan_request,
)

_OPERATIONS = [REPOSITORY_CHANGE_OPERATION, SCAN_REQUEST_OPERATION]


@dataclass(frozen=True, slots=True)
class PostgresCodeSecurityScanRequestQueueConfig:
    dsn: str = ""
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    worker_id: str = "core-code-security-scan"
    lease_seconds: int = 3_600
    restricted_access: bool = False


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
        if self._config.restricted_access:
            rows = await self._fetch_all(
                "SELECT key, value FROM public.fdai_code_security_claim("
                "%(claim_id)s, %(worker_id)s, %(lease_seconds)s)",
                {
                    "claim_id": claim_id,
                    "worker_id": self._config.worker_id,
                    "lease_seconds": self._config.lease_seconds,
                },
            )
        else:
            rows = await self._claim_unrestricted(claim_id)
        return self._parse_claim(rows, claim_id)

    async def _claim_unrestricted(self, claim_id: str) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                 WHERE key LIKE %(prefix)s
                   AND value ->> 'family' = 'operations'
                   AND value ->> 'operation' = ANY(%(operations)s)
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
                "operations": _OPERATIONS,
                "claim_id": claim_id,
                "worker_id": self._config.worker_id,
                "lease_seconds": self._config.lease_seconds,
            },
        )

    @staticmethod
    def _parse_claim(rows: list[dict[str, Any]], claim_id: str) -> ClaimedScanRequest | None:
        if not rows:
            return None
        key, record = rows[0].get("key"), rows[0].get("value")
        if not isinstance(key, str) or not isinstance(record, Mapping):
            raise ValueError("code-security scan request claim is malformed")
        attempt = record.get("attempt")
        operation = str(record.get("operation"))
        return ClaimedScanRequest(
            key=key,
            claim_id=str(record.get("claim_id") or claim_id),
            request=parse_scan_request(record),
            attempt=attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else 1,
            operation=operation,
            change=parse_repository_change(record)
            if operation == REPOSITORY_CHANGE_OPERATION
            else None,
        )

    async def mark_completed(
        self, *, key: str, claim_id: str, result: Mapping[str, object]
    ) -> bool:
        return await self._mark(
            key=key,
            claim_id=claim_id,
            update={"dispatch_status": "published", "request_result": dict(result)},
        )

    async def mark_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool:
        return await self._mark(
            key=key,
            claim_id=claim_id,
            update={"dispatch_status": "rejected", "rejection_reason": reason_code},
        )

    async def _mark(self, *, key: str, claim_id: str, update: Mapping[str, object]) -> bool:
        closed = {**dict(update), "closed_at": datetime.now(UTC).isoformat()}
        if self._config.restricted_access:
            rows = await self._fetch_all(
                "SELECT public.fdai_code_security_close("
                "%(key)s, %(claim_id)s, %(update)s::jsonb) AS closed",
                {"key": key, "claim_id": claim_id, "update": json.dumps(closed)},
            )
            closed_value = rows[0].get("closed") if len(rows) == 1 else None
            if not isinstance(closed_value, bool):
                raise ValueError("code-security close returned no boolean")
            return closed_value
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
            if self._config.restricted_access:
                await connection.execute("SET LOCAL ROLE fdai_code_security_worker")
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
