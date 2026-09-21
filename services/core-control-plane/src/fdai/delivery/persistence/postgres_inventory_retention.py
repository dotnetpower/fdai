"""Reclaim terminal inventory candidates only after their delivery evidence permits it."""

from __future__ import annotations

from typing import Any

import psycopg

from fdai.delivery.inventory_collection import collection_key
from fdai.delivery.inventory_configuration_events import (
    INVENTORY_CONFIGURATION_DELIVERY_KEY,
    configuration_delivery_key,
    configuration_delivery_pending,
)


async def require_snapshot_capacity(connection: psycopg.AsyncConnection[Any]) -> None:
    """Pending evidence is retained; backpressure stops new attempts before provider reads."""
    await prune_terminal_snapshots(connection)
    cursor = await connection.execute("SELECT count(*) AS count FROM inventory_snapshot")
    row = await cursor.fetchone()
    if row is None or row["count"] >= 128:
        raise ValueError("inventory snapshot retention pressure requires delivery recovery")


async def prune_terminal_snapshots(connection: psycopg.AsyncConnection[Any]) -> int:
    """Keep three terminal snapshots per status and all unacknowledged delivery generations."""
    cursor = await connection.execute(
        "SELECT id, status FROM ("
        "SELECT id, status, ROW_NUMBER() OVER ("
        "PARTITION BY status ORDER BY COALESCE(promoted_at, completed_at, started_at) DESC, id DESC"
        ") AS retained_rank FROM inventory_snapshot "
        "WHERE status IN ('superseded', 'failed')"
        ") terminal WHERE retained_rank > 3 ORDER BY id LIMIT 256"
    )
    snapshot_ids = []
    for row in await cursor.fetchall():
        generation = str(row["id"])
        key = configuration_delivery_key(generation)
        markers = await connection.execute(
            "SELECT key,value FROM state_kv WHERE key=ANY(%s::text[]) FOR SHARE",
            ([key, key + ":projection", INVENTORY_CONFIGURATION_DELIVERY_KEY],),
        )
        retained = {item["key"]: item["value"] for item in await markers.fetchall()}
        delivery = retained.get(key)
        legacy = retained.get(INVENTORY_CONFIGURATION_DELIVERY_KEY)
        if delivery is None and isinstance(legacy, dict) and legacy.get("generation") == generation:
            delivery = legacy
        if delivery is None and row["status"] == "failed":
            snapshot_ids.append(generation)
            continue
        if not isinstance(delivery, dict) or delivery.get("generation") != generation:
            continue
        try:
            pending = configuration_delivery_pending(delivery, generation=generation)
        except ValueError:
            continue
        projection = retained.get(key + ":projection")
        if (
            pending
            or not isinstance(projection, dict)
            or any(
                projection.get(field) != value
                for field, value in delivery.items()
                if field != "status"
            )
            or projection.get("status") != "projected"
        ):
            continue
        snapshot_ids.append(generation)
    if not snapshot_ids:
        return 0
    await connection.execute(
        "DELETE FROM state_kv WHERE EXISTS ("
        "SELECT 1 FROM unnest(%s::text[]) AS doomed(prefix) "
        "WHERE starts_with(state_kv.key, doomed.prefix || ':')"
        ")",
        ([collection_key(generation) for generation in snapshot_ids],),
    )
    await connection.execute(
        "DELETE FROM inventory_snapshot WHERE id=ANY(%s::text[])",
        (snapshot_ids,),
    )
    return len(snapshot_ids)
