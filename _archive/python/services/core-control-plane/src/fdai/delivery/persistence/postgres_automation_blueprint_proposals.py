"""Durable Operator proposal queue for automation blueprint decisions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai.core.scheduler.blueprints.proposals import AutomationBlueprintReviewProposal

_OPERATIONS = (
    "automation_blueprint.accept",
    "automation_blueprint.reject",
    "automation_blueprint.materialize",
)


@dataclass(frozen=True, slots=True)
class PostgresAutomationBlueprintProposalQueueConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


@dataclass(frozen=True, slots=True)
class ClaimedAutomationBlueprintProposal:
    key: str
    claim_id: str
    proposal: AutomationBlueprintReviewProposal


class PostgresAutomationBlueprintProposalQueue:
    """Claim and close queued Operator decisions without executing in the route."""

    def __init__(self, config: PostgresAutomationBlueprintProposalQueueConfig) -> None:
        if not config.dsn.strip():
            raise ValueError("automation blueprint proposal queue dsn MUST be non-empty")
        self._config = config

    async def claim(
        self,
        *,
        worker_id: str = "core-automation-blueprint-review",
        lease_seconds: int = 120,
    ) -> ClaimedAutomationBlueprintProposal | None:
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        rows = await self._fetch_all(
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
                 ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                          value ->> 'accepted_at', key
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
                "operations": list(_OPERATIONS),
                "claim_id": claim_id,
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        record = rows[0].get("value")
        if not isinstance(key, str) or not isinstance(record, Mapping):
            raise ValueError("automation blueprint proposal claim is malformed")
        return ClaimedAutomationBlueprintProposal(
            key=key,
            claim_id=str(record.get("claim_id") or claim_id),
            proposal=_proposal_from_record(record),
        )

    async def mark_applied(self, *, key: str, claim_id: str) -> bool:
        return await self._mark(key=key, claim_id=claim_id, status="published")

    async def mark_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool:
        return await self._mark(
            key=key,
            claim_id=claim_id,
            status="rejected",
            extra={"rejection_reason": reason_code},
        )

    async def release(self, *, key: str, claim_id: str) -> bool:
        return await self._mark(
            key=key,
            claim_id=claim_id,
            status="pending",
            extra={"claim_id": None, "claim_worker_id": None, "claim_expires_at": None},
        )

    async def _mark(
        self,
        *,
        key: str,
        claim_id: str,
        status: str,
        extra: Mapping[str, object] | None = None,
    ) -> bool:
        update = {"dispatch_status": status, **dict(extra or {})}
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = value || %(update)s::jsonb, updated_at = NOW()
             WHERE key = %(key)s AND value ->> 'claim_id' = %(claim_id)s
         RETURNING key
            """,
            {"key": key, "claim_id": claim_id, "update": json.dumps(update)},
        )
        return bool(rows)

    async def _fetch_all(
        self,
        query: str,
        parameters: Mapping[str, object] | None = None,
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


def _proposal_from_record(record: Mapping[str, object]) -> AutomationBlueprintReviewProposal:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("automation blueprint proposal record payload is malformed")
    event_payload = payload.get("payload")
    roles = payload.get("principal_roles", ())
    if not isinstance(event_payload, Mapping) or not isinstance(roles, list | tuple):
        raise ValueError("automation blueprint proposal event payload is malformed")
    return AutomationBlueprintReviewProposal(
        operation=_required_str(record, "operation"),
        principal_id=_required_str(record, "principal_id"),
        idempotency_key=_required_str(record, "idempotency_key"),
        payload=event_payload,
        principal_roles=tuple(str(role) for role in roles),
        proposal_id=_optional_str(record.get("proposal_id")),
    )


def _required_str(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"automation blueprint proposal {field} is malformed")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "ClaimedAutomationBlueprintProposal",
    "PostgresAutomationBlueprintProposalQueue",
    "PostgresAutomationBlueprintProposalQueueConfig",
]
