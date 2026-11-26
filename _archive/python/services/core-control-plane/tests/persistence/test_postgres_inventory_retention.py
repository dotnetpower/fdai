"""Terminal inventory retention must preserve unfinished delivery and hashed staging."""

from __future__ import annotations

import pytest
from fdai.delivery.inventory_collection import collection_key
from fdai.delivery.inventory_configuration_events import configuration_delivery_key
from fdai.delivery.persistence.postgres_inventory_retention import require_snapshot_capacity
from fdai.delivery.persistence.postgres_inventory_snapshot import _prune_terminal_snapshots
from psycopg.types.json import Jsonb

from tests.persistence.test_postgres_ontology_instance import _isolated_replacement_store


@pytest.mark.parametrize(
    "condition",
    [
        "pending",
        "missing",
        "malformed",
        "mismatch",
        "completed",
        "failed",
        "legacy_pending",
        "authority",
        "wrong_generation",
        "missing_projection",
    ],
)
async def test_retention_requires_completed_delivery_and_uses_hashed_chunk_keys(condition):
    async with _isolated_replacement_store() as store:
        generation = "old-generation"
        delivery_key = configuration_delivery_key(generation)
        prefix = collection_key(generation)
        delivery = {
            "schema_version": "1.0.0",
            "generation": generation,
            "observation_digest": "sha256:" + "a" * 64,
            "resource_count": 1,
            "execution_authority": False,
            "status": "completed" if condition == "completed" else "pending",
        }
        projection = {**delivery, "status": "projected"}
        if condition == "malformed":
            delivery["resource_count"] = True
        elif condition == "mismatch":
            delivery["status"] = "completed"
            projection["observation_digest"] = "sha256:" + "b" * 64
        elif condition == "authority":
            delivery["status"] = "completed"
            delivery["execution_authority"] = True
        elif condition == "wrong_generation":
            delivery["status"] = "completed"
            delivery["generation"] = "other-generation"
        elif condition == "missing_projection":
            delivery["status"] = "completed"
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_snapshot (id TEXT PRIMARY KEY,status TEXT,"
                "promoted_at TIMESTAMPTZ,completed_at TIMESTAMPTZ,started_at TIMESTAMPTZ)"
            )
            await connection.execute(
                "INSERT INTO inventory_snapshot VALUES (%s,%s,NOW()-INTERVAL '1 day',NOW(),NOW())",
                (generation, "failed" if condition == "failed" else "superseded"),
            )
            for index in range(3):
                await connection.execute(
                    "INSERT INTO inventory_snapshot VALUES (%s,%s,NOW(),NOW(),NOW())",
                    (f"new-{index}", "failed" if condition == "failed" else "superseded"),
                )
            await connection.execute(
                "INSERT INTO state_kv (key,value) VALUES (%s,'{}'),(%s,'{}'),(%s,'{}')",
                (
                    prefix + ":chunk:00000000",
                    prefix + ":checkpoint",
                    collection_key("other") + ":chunk:00000000",
                ),
            )
            if condition not in {"missing", "failed"}:
                await connection.execute(
                    "INSERT INTO state_kv (key,value) VALUES (%s,%s),(%s,%s)",
                    (
                        "inventory-configuration:delivery"
                        if condition == "legacy_pending"
                        else delivery_key,
                        Jsonb(delivery),
                        delivery_key + ":projection",
                        Jsonb(projection),
                    ),
                )
                if condition == "missing_projection":
                    await connection.execute(
                        "DELETE FROM state_kv WHERE key=%s", (delivery_key + ":projection",)
                    )
        async with await store._connect() as connection:
            removed = await _prune_terminal_snapshots(connection)
            assert removed == (1 if condition in {"completed", "failed"} else 0)
            cursor = await connection.execute(
                "SELECT key FROM state_kv WHERE starts_with(key,%s)", (prefix,)
            )
            assert len(await cursor.fetchall()) == (0 if removed else 2)
            cursor = await connection.execute(
                "SELECT 1 FROM state_kv WHERE key=%s",
                (collection_key("other") + ":chunk:00000000",),
            )
            assert await cursor.fetchone() is not None


@pytest.mark.parametrize("count", [127, 128, 129])
async def test_pending_snapshot_pressure_blocks_without_deleting_evidence(count):
    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_snapshot (id TEXT PRIMARY KEY,status TEXT,"
                "promoted_at TIMESTAMPTZ,completed_at TIMESTAMPTZ,started_at TIMESTAMPTZ)"
            )
            await connection.execute(
                "INSERT INTO inventory_snapshot SELECT 'pending-' || sequence,"
                "'superseded',NOW(),NOW(),NOW() FROM generate_series(1,%s) AS sequence",
                (count,),
            )
            if count >= 128:
                with pytest.raises(ValueError, match="retention pressure"):
                    await require_snapshot_capacity(connection)
            else:
                await require_snapshot_capacity(connection)
            cursor = await connection.execute("SELECT count(*) AS count FROM inventory_snapshot")
            assert (await cursor.fetchone())["count"] == count
