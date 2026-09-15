"""PostgreSQL leases for content-free assignment request transport."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai_operator_service.assignment_outbox import (
    AssignmentNoticeBridge,
    AssignmentNoticeDrainer,
    AssignmentNoticePublisher,
    AssignmentProposalClaim,
)
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig


@dataclass(frozen=True, slots=True)
class PostgresAssignmentOutbox:
    """Claim only the existing IAM assignment operations with a two-minute lease.

    The source request fields never change. Claim status is transport state and is not a human
    review, Core assignment state, IAM receipt, or source mutation authorization.
    """

    config: PostgresFamilyStoreConfig

    async def _query(self, sql: str, parameters: Mapping[str, object]) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            normalize_psycopg_dsn(self.config.dsn),
            row_factory=dict_row,
            connect_timeout=self.config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.config.statement_timeout_ms),),
                )
                cursor = await connection.execute(sql, parameters)
                return list(await cursor.fetchall())

    async def claim(self) -> AssignmentProposalClaim | None:
        claim_id = str(uuid4())
        rows = await self._query(
            """
            WITH candidate AS (
                SELECT request.key FROM state_kv AS request
                 LEFT JOIN operator_assignment_receipt AS receipt
                   ON receipt.proposal_ref = request.key
                 WHERE starts_with(request.key, 'operator-proposal:iam:')
                   AND request.value ->> 'operation' IN
                       ('assignments.create', 'assignments.submit', 'assignments.review')
                   AND (request.value ->> 'dispatch_status' = 'pending'
                       OR (request.value ->> 'dispatch_status' = 'claimed'
                           AND (request.value ->> 'claim_expires_at')::timestamptz <= NOW()))
                   AND (
                       request.value ->> 'operation' = 'assignments.create'
                       OR COALESCE(receipt.recorded_at, request.updated_at)
                           <= NOW() - interval '5 minutes'
                       OR EXISTS (
                           SELECT 1 FROM state_kv AS binding JOIN state_kv AS snapshot
                             ON snapshot.key = CASE
                                 WHEN binding.value ->> 'case_kind' = 'scoped_duty'
                                 THEN 'human_assignment:scoped-case:'
                                 ELSE 'human_assignment:case:' END ||
                                 (binding.value ->> 'case_id')
                            WHERE binding.key = 'human_assignment:operator-case:' ||
                                  (request.value -> 'payload' ->> 'case_id')
                              AND snapshot.value -> 'revision' >=
                                  request.value -> 'payload' -> 'expected_revision'
                       )
                   )
                 ORDER BY COALESCE((request.value ->> 'transport_attempt')::integer, 0),
                          request.value ->> 'accepted_at', request.key
                 FOR UPDATE OF request SKIP LOCKED LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                    'dispatch_status', 'claimed', 'claim_id', %(claim_id)s::text,
                    'claim_expires_at', NOW() + interval '120 seconds',
                    'transport_attempt',
                    COALESCE((proposal.value ->> 'transport_attempt')::integer, 0) + 1),
                   updated_at = NOW()
              FROM candidate WHERE proposal.key = candidate.key
            RETURNING proposal.key, proposal.value
            """,
            {"claim_id": claim_id},
        )
        if not rows:
            return None
        record = rows[0]["value"]
        if isinstance(record, str):
            record = json.loads(record)
        if not isinstance(record, Mapping):
            raise ValueError("assignment outbox source record is malformed")
        return AssignmentProposalClaim(str(rows[0]["key"]), claim_id, dict(record))

    async def finish(self, claim: AssignmentProposalClaim, *, rejected: bool = False) -> bool:
        return bool(await self._transition(claim, "rejected" if rejected else "published"))

    async def release(self, claim: AssignmentProposalClaim) -> None:
        await self._transition(claim, "pending")

    async def _transition(self, claim: AssignmentProposalClaim, state: str) -> list[dict[str, Any]]:
        return await self._query(
            """
            UPDATE state_kv SET value = value || jsonb_build_object(
                'dispatch_status', %(state)s::text), updated_at = NOW()
             WHERE key = %(key)s AND starts_with(key, 'operator-proposal:iam:')
               AND value ->> 'dispatch_status' = 'claimed'
               AND value ->> 'claim_id' = %(claim_id)s
               AND (value ->> 'claim_expires_at')::timestamptz > NOW()
            RETURNING key
            """,
            {"state": state, "key": claim.key, "claim_id": claim.claim_id},
        )


def build_assignment_notice_bridge(
    environment: OperatorEnvironment, publisher: AssignmentNoticePublisher | None
) -> AssignmentNoticeBridge | None:
    """Bind the same local/deployed transport without acquiring credentials at construction."""
    if environment.database_url is None or publisher is None:
        return None
    store = PostgresAssignmentOutbox(
        PostgresFamilyStoreConfig(
            dsn=environment.database_url,
            connect_timeout_s=environment.database_connect_timeout_s,
            statement_timeout_ms=environment.database_statement_timeout_ms,
        )
    )
    return AssignmentNoticeBridge(AssignmentNoticeDrainer(store, publisher))


__all__ = ["PostgresAssignmentOutbox", "build_assignment_notice_bridge"]
