"""PostgreSQL correction closure for retained inventory observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.operational_history_lifecycle import build_correction_receipt


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("observation lifecycle record MUST be an object")
    return value


def _content_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


async def close_observation_corrections(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation: str,
    projection_watermark: int,
    closed_at: datetime,
    scope_ref: str | None = None,
) -> None:
    """Close correction partitions only after the ontology projection advances.

    ``scope_ref`` narrows the closure to one exact observation scope. The production
    projection path leaves it unset so every replayed correction closes, while a
    bounded caller can close only the corrections it actually replayed.
    """

    manifest_cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
    )
    manifest_row = await manifest_cursor.fetchone()
    manifest = _mapping(manifest_row["value"]) if manifest_row is not None else {}
    graph_digest = manifest.get("manifest_digest")
    if not isinstance(graph_digest, str) or not graph_digest.startswith("sha256:"):
        raise ValueError("ontology manifest digest is unavailable for correction closure")
    cursor = await connection.execute(
        "SELECT partition_id, correction_of FROM inventory_observation_partition "
        "WHERE partition_kind='correction' AND state='correction_pending' "
        "AND last_watermark<=%s AND (%s::text IS NULL OR scope_ref=%s) "
        "ORDER BY partition_id FOR UPDATE",
        (projection_watermark, scope_ref, scope_ref),
    )
    for row in await cursor.fetchall():
        partition_id = str(row["partition_id"])
        corrected_partition_id = str(row["correction_of"])
        checkpoint_cursor = await connection.execute(
            "SELECT checkpoint_id FROM inventory_observation_checkpoint "
            "WHERE partition_id=ANY(%s::text[]) AND valid "
            "ORDER BY checkpoint_id",
            ([partition_id, corrected_partition_id],),
        )
        checkpoint_ids = tuple(
            str(item["checkpoint_id"]) for item in await checkpoint_cursor.fetchall()
        )
        correction_manifest_digest = _content_digest(
            {
                "correction_partition_id": partition_id,
                "affected_checkpoint_ids": list(checkpoint_ids),
            }
        )
        replay_receipt_digest = _content_digest(
            {
                "generation": generation,
                "projection_watermark": projection_watermark,
                "graph_digest": graph_digest,
            }
        )
        receipt = build_correction_receipt(
            correction_partition_id=partition_id,
            affected_checkpoint_ids=checkpoint_ids,
            correction_manifest_digest=correction_manifest_digest,
            replay_receipt_digest=replay_receipt_digest,
            resulting_graph_digest=graph_digest,
            projection_watermark=projection_watermark,
            closed_at=closed_at,
        )
        record = {
            "receipt_id": receipt.receipt_id,
            "correction_partition_id": receipt.correction_partition_id,
            "affected_checkpoint_ids": list(receipt.affected_checkpoint_ids),
            "correction_manifest_digest": receipt.correction_manifest_digest,
            "replay_receipt_digest": receipt.replay_receipt_digest,
            "resulting_graph_digest": receipt.resulting_graph_digest,
            "projection_watermark": receipt.projection_watermark,
            "closed_at": receipt.closed_at.isoformat(),
            "complete": receipt.complete,
            "digest": receipt.digest,
        }
        await connection.execute(
            "INSERT INTO inventory_observation_correction_receipt "
            "(receipt_id, correction_partition_id, projection_watermark, complete, "
            "record, closed_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (receipt_id) DO NOTHING",
            (
                receipt.receipt_id,
                receipt.correction_partition_id,
                receipt.projection_watermark,
                receipt.complete,
                Jsonb(record),
                receipt.closed_at,
            ),
        )
        await connection.execute(
            "UPDATE inventory_observation_partition "
            "SET state='checkpointed', updated_at=%s WHERE partition_id=%s "
            "AND state='correction_pending'",
            (closed_at, partition_id),
        )


__all__ = ["close_observation_corrections"]
