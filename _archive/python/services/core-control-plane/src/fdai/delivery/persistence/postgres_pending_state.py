"""Read pending same-type object observations from one repeatable-read snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.ontology_platform.pending_state_coverage import (
    PendingObservation,
    PendingStateDescriptor,
    PendingStateDescriptorUnavailableError,
)
from fdai.delivery.inventory_sync import INVENTORY_ACTIVE_SCOPE_CHECKPOINT_KEY

# The pending predicate matches the source-coverage gap exactly: an object observation of the
# requested types above the projection fence that the active generation does not already cover.
_DESCRIPTOR_SQL = (
    "SELECT active.snapshot_id, pending.observation_id, pending.subject_ref, "
    "pending.subject_type, pending.provider_ref, pending.mutation_kind, "
    "pending.tombstone_confirmed, pending.effective_at "
    "FROM inventory_active AS active "
    "JOIN inventory_snapshot AS snapshot ON snapshot.id=active.snapshot_id "
    "LEFT JOIN state_kv AS observation_watermarks "
    "ON observation_watermarks.key='inventory-observation:watermarks' "
    "LEFT JOIN state_kv AS active_checkpoint ON active_checkpoint.key=%s "
    "LEFT JOIN LATERAL (SELECT journal.* FROM jsonb_array_elements_text(snapshot.scopes) "
    "AS pending_scope(scope) JOIN inventory_observation_journal AS journal "
    "ON journal.scope_ref=pending_scope.scope "
    "WHERE journal.watermark>CASE WHEN "
    "active_checkpoint.value->>'generation'=active.snapshot_id "
    "AND active_checkpoint.value->'scope_refs'=snapshot.scopes "
    "THEN COALESCE((active_checkpoint.value->>'projection_high_watermark')::bigint, 0) "
    "ELSE COALESCE("
    "(observation_watermarks.value->>'ontology_projection_watermark')::bigint, 0) END "
    "AND journal.subject_kind='object' AND journal.subject_type=ANY(%s::text[]) "
    "AND NOT (journal.source_revision=active.snapshot_id "
    "OR journal.effective_at<=snapshot.started_at) "
    "ORDER BY journal.watermark LIMIT %s) AS pending ON TRUE "
    "WHERE active.singleton=TRUE"
)


class PostgresPendingStateDescriptorReader:
    """Return the active generation and its bounded pending observations atomically."""

    def __init__(self, *, dsn: str, statement_timeout_ms: int = 5_000) -> None:
        if not dsn.strip():
            raise ValueError("pending-state descriptor DSN MUST be non-empty")
        self._dsn = dsn
        self._timeout_ms = statement_timeout_ms

    async def pending_state_descriptor(
        self,
        *,
        subject_types: Sequence[str],
        limit: int,
    ) -> PendingStateDescriptor:
        if not subject_types or not 1 <= limit <= 10:
            raise ValueError("pending-state descriptor needs types and a limit from 1 to 10")
        try:
            async with await psycopg.AsyncConnection.connect(
                self._dsn, row_factory=dict_row
            ) as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    await conn.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(self._timeout_ms),),
                    )
                    cursor = await conn.execute(
                        _DESCRIPTOR_SQL,
                        (INVENTORY_ACTIVE_SCOPE_CHECKPOINT_KEY, list(subject_types), limit + 1),
                    )
                    rows = await cursor.fetchall()
        except psycopg.Error as exc:
            raise PendingStateDescriptorUnavailableError(
                "pending-state descriptor read failed"
            ) from exc
        return descriptor_from_rows(rows, limit=limit)


def descriptor_from_rows(rows: Sequence[dict[str, Any]], *, limit: int) -> PendingStateDescriptor:
    """Build the descriptor; one extra row beyond the limit marks overflow."""

    if not rows:
        return PendingStateDescriptor(generation=None, observations=(), overflow=False)
    generation = rows[0].get("snapshot_id")
    observations = tuple(
        PendingObservation(
            observation_id=str(row["observation_id"]),
            subject_ref=str(row["subject_ref"]),
            subject_type=str(row["subject_type"]),
            provider_ref=str(row["provider_ref"]) if row.get("provider_ref") else None,
            mutation_kind=str(row["mutation_kind"]),
            tombstone=bool(row["tombstone_confirmed"]),
            effective_at=row["effective_at"],
        )
        for row in rows
        if row.get("observation_id") is not None
    )
    return PendingStateDescriptor(
        generation=str(generation) if generation is not None else None,
        observations=observations[:limit],
        overflow=len(observations) > limit,
    )


__all__ = ["PostgresPendingStateDescriptorReader", "descriptor_from_rows"]
