"""Transactional append and watermark helpers for the inventory journal."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from fdai.delivery.persistence.postgres_inventory_observation_records import (
    mapping as _mapping,
)
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    observation_params as _observation_params,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    nonnegative_watermark as _nonnegative_int,
)
from fdai.shared.providers.inventory_observation import NormalizedInventoryObservation

INVENTORY_OBSERVATION_WATERMARK_KEY: Final[str] = "inventory-observation:watermarks"
_WRITE_BATCH_SIZE = 1000
_INSERT_OBSERVATION_SQL = (
    "INSERT INTO inventory_observation_journal "
    "(observation_id, content_digest, schema_version, idempotency_key, "
    "subject_kind, observation_kind, mutation_kind, subject_ref, subject_type, "
    "properties, property_mask, properties_complete, links_complete, "
    "tombstone_confirmed, provider_ref, scope_ref, operation, operation_status, "
    "source_identity, source_event_id, source_revision, effective_at, observed_at, "
    "evidence_cutoff, recorded_at, ingested_at, provider_event_at, "
    "from_id, from_type, link_type, to_id, to_type) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, "
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s, %s) ON CONFLICT (idempotency_key, subject_kind, subject_ref) DO NOTHING"
)


@dataclass(frozen=True, slots=True)
class InventoryObservationAppendResult:
    """Result of one atomic journal append."""

    high_watermark: int
    inserted: int


async def append_records(
    connection: psycopg.AsyncConnection[Any],
    observations: Sequence[NormalizedInventoryObservation],
) -> InventoryObservationAppendResult:
    if not observations:
        cursor = await connection.execute(
            "SELECT COALESCE(MAX(watermark), 0) AS high_watermark "
            "FROM inventory_observation_journal"
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("inventory observation journal high watermark is unavailable")
        return InventoryObservationAppendResult(int(row["high_watermark"]), 0)
    inserted = 0
    retained_watermarks: list[int] = []
    for offset in range(0, len(observations), _WRITE_BATCH_SIZE):
        chunk = observations[offset : offset + _WRITE_BATCH_SIZE]
        cursor = connection.cursor()
        await cursor.executemany(
            _INSERT_OBSERVATION_SQL,
            [_observation_params(item) for item in chunk],
        )
        inserted += max(0, cursor.rowcount)
        keys = sorted({item.idempotency_key for item in chunk})
        retained_cursor = await connection.execute(
            "SELECT watermark, idempotency_key, subject_kind, subject_ref, content_digest "
            "FROM inventory_observation_journal WHERE idempotency_key=ANY(%s::text[])",
            (keys,),
        )
        retained = await retained_cursor.fetchall()
        retained_by_key = {
            (
                str(row["idempotency_key"]),
                str(row["subject_kind"]),
                str(row["subject_ref"]),
            ): row
            for row in retained
        }
        for item in chunk:
            key = (item.idempotency_key, item.subject_kind.value, item.subject_ref)
            row = retained_by_key.get(key)
            if row is None or str(row["content_digest"]) != item.content_digest:
                raise ValueError("inventory observation idempotency key changed content")
            retained_watermarks.append(int(row["watermark"]))
    high_watermark = max(retained_watermarks)
    await update_watermark_state(connection, journal_watermark=high_watermark)
    return InventoryObservationAppendResult(high_watermark, inserted)


async def update_watermark_state(
    connection: psycopg.AsyncConnection[Any],
    *,
    journal_watermark: int | None = None,
    overlay_watermark: int | None = None,
    ontology_watermark: int | None = None,
    ontology_generation: str | None = None,
) -> None:
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s FOR UPDATE",
        (INVENTORY_OBSERVATION_WATERMARK_KEY,),
    )
    row = await cursor.fetchone()
    state = _mapping(row["value"]) if row is not None else {}
    current_journal = _nonnegative_int(state.get("journal_high_watermark"))
    current_overlay = _nonnegative_int(state.get("overlay_projection_watermark"))
    current_ontology = _nonnegative_int(state.get("ontology_projection_watermark"))
    next_journal = max(current_journal, journal_watermark or 0)
    next_overlay = max(current_overlay, overlay_watermark or 0)
    next_ontology = max(current_ontology, ontology_watermark or 0)
    if next_overlay > next_journal or next_ontology > next_journal:
        raise ValueError("inventory observation projection watermark exceeds journal")
    pending_cursor = await connection.execute(
        "SELECT COUNT(*) AS pending FROM inventory_observation_pending_tombstone"
    )
    pending_row = await pending_cursor.fetchone()
    pending = int(pending_row["pending"]) if pending_row is not None else 0
    value = {
        "schema_version": "1.0.0",
        "journal_high_watermark": next_journal,
        "overlay_projection_watermark": next_overlay,
        "ontology_projection_watermark": next_ontology,
        "ontology_generation": ontology_generation or state.get("ontology_generation"),
        "pending_tombstones": pending,
        "mode": "shadow",
    }
    await connection.execute(
        "INSERT INTO state_kv (key, value, updated_at) VALUES (%s, %s::jsonb, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
        (
            INVENTORY_OBSERVATION_WATERMARK_KEY,
            json.dumps(value, sort_keys=True, separators=(",", ":")),
        ),
    )


__all__ = [
    "INVENTORY_OBSERVATION_WATERMARK_KEY",
    "InventoryObservationAppendResult",
    "append_records",
    "update_watermark_state",
]
