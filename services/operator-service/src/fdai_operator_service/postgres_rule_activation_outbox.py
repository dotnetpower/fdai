"""PostgreSQL leases for content-free Rule activation proposal transport."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_operator_service.rule_activation_outbox import (
    RuleActivationNoticeBridge,
    RuleActivationNoticeDrainer,
    RuleActivationNoticePublisher,
    RuleActivationProposalClaim,
)


@dataclass(frozen=True, slots=True)
class PostgresRuleActivationOutbox:
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

    async def claim(self) -> RuleActivationProposalClaim | None:
        claim_id = str(uuid4())
        rows = await self._query(
            """
            WITH candidate AS (
                SELECT key FROM state_kv
                 WHERE starts_with(key, 'operator-proposal:workflow:')
                   AND value ->> 'operation' IN
                       ('rule.activation-request', 'rule.activation-approve')
                   AND (
                       value ->> 'operation' = 'rule.activation-request'
                       OR EXISTS (
                           SELECT 1 FROM state_kv AS source_request
                            WHERE starts_with(
                                source_request.key,
                                'operator-proposal:workflow:'
                            )
                              AND source_request.value ->> 'operation' =
                                  'rule.activation-request'
                              AND source_request.value ->> 'proposal_id' =
                                  value -> 'payload' -> 'path_parameters' ->> 'request_id'
                              AND source_request.value ->> 'dispatch_status' = 'published'
                       )
                   )
                   AND (value ->> 'dispatch_status' = 'pending'
                       OR (value ->> 'dispatch_status' = 'claimed'
                           AND (value ->> 'claim_expires_at')::timestamptz <= NOW()))
                 ORDER BY COALESCE((value ->> 'transport_attempt')::integer, 0),
                          value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED LIMIT 1
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
            raise ValueError("Rule activation outbox source record is malformed")
        return RuleActivationProposalClaim(str(rows[0]["key"]), claim_id, dict(record))

    async def finish(
        self,
        claim: RuleActivationProposalClaim,
        *,
        rejected: bool = False,
    ) -> bool:
        return bool(await self._transition(claim, "rejected" if rejected else "published"))

    async def release(self, claim: RuleActivationProposalClaim) -> None:
        await self._transition(claim, "pending")

    async def _transition(
        self,
        claim: RuleActivationProposalClaim,
        state: str,
    ) -> list[dict[str, Any]]:
        return await self._query(
            """
            UPDATE state_kv SET value = value || jsonb_build_object(
                'dispatch_status', %(state)s::text), updated_at = NOW()
             WHERE key = %(key)s AND starts_with(key, 'operator-proposal:workflow:')
               AND value ->> 'operation' IN
                   ('rule.activation-request', 'rule.activation-approve')
               AND value ->> 'dispatch_status' = 'claimed'
               AND value ->> 'claim_id' = %(claim_id)s
               AND (value ->> 'claim_expires_at')::timestamptz > NOW()
            RETURNING key
            """,
            {"state": state, "key": claim.key, "claim_id": claim.claim_id},
        )


def build_rule_activation_notice_bridge(
    environment: OperatorEnvironment,
    publisher: RuleActivationNoticePublisher | None,
) -> RuleActivationNoticeBridge | None:
    if environment.database_url is None or publisher is None:
        return None
    store = PostgresRuleActivationOutbox(
        PostgresFamilyStoreConfig(
            dsn=environment.database_url,
            connect_timeout_s=environment.database_connect_timeout_s,
            statement_timeout_ms=environment.database_statement_timeout_ms,
        )
    )
    return RuleActivationNoticeBridge(RuleActivationNoticeDrainer(store, publisher))


__all__ = ["PostgresRuleActivationOutbox", "build_rule_activation_notice_bridge"]
