"""Compute global retention and active-scope inventory projection checkpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg


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


__all__ = ["active_scope_projection_watermark", "global_projection_watermark"]
