"""Compute global retention, active-scope, and covered-delta inventory projection fences."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_inventory_observation_records import mapping
from fdai.delivery.persistence.postgres_inventory_observation_write import (
    INVENTORY_OBSERVATION_WATERMARK_KEY,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    nonnegative_watermark,
)


async def active_scope_projection_watermark(
    connection: psycopg.AsyncConnection[Any],
    *,
    high_watermark: int,
    generation: str,
    snapshot_started_at: datetime,
    scope_refs: tuple[str, ...],
) -> int:
    """Find the contiguous current-graph fence for the active snapshot scopes."""

    if not scope_refs:
        raise ValueError("active inventory snapshot scopes MUST NOT be empty")
    cursor = await connection.execute(
        "SELECT COALESCE(MIN(watermark) - 1, %s) AS projection_watermark "
        "FROM inventory_observation_journal "
        "WHERE scope_ref=ANY(%s::text[]) "
        "AND NOT (source_revision=%s OR effective_at<=%s)",
        (
            high_watermark,
            list(scope_refs),
            generation,
            snapshot_started_at,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("inventory observation projection watermark is unavailable")
    return min(high_watermark, int(row["projection_watermark"]))


async def global_projection_watermark(
    connection: psycopg.AsyncConnection[Any],
    *,
    high_watermark: int,
    current_projection: int,
    generation: str,
    snapshot_started_at: datetime,
    scope_refs: tuple[str, ...],
) -> int:
    """Preserve the contiguous all-scope fence used by retention and replay."""

    cursor = await connection.execute(
        "SELECT COALESCE(MIN(watermark) - 1, %s) AS projection_watermark "
        "FROM inventory_observation_journal "
        "WHERE watermark>%s AND NOT (source_revision=%s OR ("
        "effective_at<=%s AND scope_ref=ANY(%s::text[])))",
        (
            high_watermark,
            current_projection,
            generation,
            snapshot_started_at,
            list(scope_refs),
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("inventory observation projection watermark is unavailable")
    return min(
        high_watermark,
        max(current_projection, int(row["projection_watermark"])),
    )


async def covered_ontology_projection_watermark(
    connection: psycopg.AsyncConnection[Any],
) -> tuple[str, int] | None:
    """Return the ontology fence across late entries that the projected generation covers.

    A realtime change recorded after promotion but covered by the active generation carries no
    ontology change. The fence may cross it only after that generation's graph commit is durable,
    so the watermark state and the ontology manifest must both name the active generation.
    """

    cursor = await connection.execute(
        "SELECT s.id, s.started_at, s.scopes, w.value AS watermarks, m.value AS manifest "
        "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
        "JOIN state_kv w ON w.key=%s "
        "JOIN state_kv m ON m.key='inventory-ontology:manifest' "
        "WHERE a.singleton=TRUE AND s.status='active'",
        (INVENTORY_OBSERVATION_WATERMARK_KEY,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    generation = str(row["id"])
    state = mapping(row["watermarks"])
    manifest = mapping(row["manifest"])
    graph_digest = manifest.get("manifest_digest")
    if (
        state.get("ontology_generation") != generation
        or manifest.get("generation") != generation
        or not isinstance(graph_digest, str)
        or not graph_digest.startswith("sha256:")
    ):
        return None
    current = nonnegative_watermark(state.get("ontology_projection_watermark"))
    high = nonnegative_watermark(state.get("journal_high_watermark"))
    if current >= high:
        return None
    fence = await global_projection_watermark(
        connection,
        high_watermark=high,
        current_projection=current,
        generation=generation,
        snapshot_started_at=row["started_at"],
        scope_refs=tuple(str(value) for value in row["scopes"]),
    )
    return (generation, fence) if fence > current else None


__all__ = [
    "active_scope_projection_watermark",
    "covered_ontology_projection_watermark",
    "global_projection_watermark",
]
