"""Transactional operator recovery for a legacy Saga checkpoint."""

from __future__ import annotations

import asyncio

from psycopg.types.json import Jsonb

from fdai.agents import SagaAuditMigration, prepare_saga_audit_migration
from fdai.delivery.persistence.postgres import _AUDIT_APPEND_LOCK_KEY, PostgresStateStore
from fdai.delivery.persistence.postgres_audit_fields import json_object

_CHECKPOINT_KEY = "pantheon/saga/audit-chain/verified-head"
_MAX_RECORDS = 50_000
_MAX_BYTES = 64 * 1_024 * 1_024


async def migrate_saga_audit_chain(
    store: PostgresStateStore,
    *,
    expected_plan_digest: str | None = None,
    legacy_writers_quiesced: bool = False,
    preserve_detached_histories: bool = False,
) -> SagaAuditMigration:
    """Dry-run by default; apply only an exact reviewed plan with atomic audit.

    The checkpoint row and shared audit lock fence modern writers in their
    normal lock order. Old writers must already be quiesced by the operator.
    No rows are deleted, rewritten, or replayed, and no authority changes.
    """
    if expected_plan_digest is not None and not legacy_writers_quiesced:
        raise ValueError("stop legacy Saga writers before applying the reviewed migration")
    async with asyncio.timeout(30):
        async with store._connection() as conn:
            async with conn.transaction():
                await store._set_statement_timeout(conn)
                await conn.execute("SET LOCAL lock_timeout = '3s'")
                cursor = await conn.execute(
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (_CHECKPOINT_KEY,),
                )
                checkpoint_row = await cursor.fetchone()
                if checkpoint_row is None:
                    raise ValueError("legacy Saga checkpoint is missing; no recovery was applied")
                await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_AUDIT_APPEND_LOCK_KEY,))
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) AS count,
                           COALESCE(SUM(octet_length(entry::text)), 0) AS bytes
                      FROM audit_log
                     WHERE action_kind = 'audit.record' AND actor = 'Saga'
                    """
                )
                size = await cursor.fetchone()
                if size is None or size["count"] > _MAX_RECORDS or size["bytes"] > _MAX_BYTES:
                    raise ValueError("legacy Saga history exceeds the reviewed migration budget")
                cursor = await conn.execute(
                    """
                    SELECT entry FROM audit_log
                     WHERE action_kind = 'audit.record' AND actor = 'Saga'
                     ORDER BY seq
                     LIMIT %s
                    """,
                    (_MAX_RECORDS + 1,),
                )
                records = await cursor.fetchall()
                plan = prepare_saga_audit_migration(
                    json_object(checkpoint_row["value"]),
                    tuple(json_object(row["entry"]) for row in records),
                )
                if expected_plan_digest is None:
                    return plan
                if plan.plan_digest != expected_plan_digest:
                    raise ValueError("Saga migration plan changed; run and review a new dry-run")
                if plan.detached_count and not preserve_detached_histories:
                    raise ValueError(
                        "explicitly acknowledge preservation of detached Saga histories"
                    )
                await conn.execute(
                    "UPDATE state_kv SET value = %s, updated_at = NOW() WHERE key = %s",
                    (Jsonb(plan.checkpoint()), _CHECKPOINT_KEY),
                )
                await store._append_audit_in_transaction(
                    conn,
                    {
                        "actor": "saga-audit-migration",
                        "owner_agent": "Saga",
                        "action_kind": "audit.chain.migrated",
                        "mode": "shadow",
                        "execution_authority": False,
                        "plan_digest": plan.plan_digest,
                        **plan.summary(),
                    },
                )
                return plan
