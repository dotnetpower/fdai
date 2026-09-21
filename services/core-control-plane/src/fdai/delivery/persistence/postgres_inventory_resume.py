"""Load one verified unfinished collection under the coordinator's existing run lock."""

from __future__ import annotations

import asyncio
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.inventory_collection import collection_context_digest, collection_key
from fdai.delivery.inventory_collection_resume import ResumedInventoryCollection
from fdai.delivery.persistence.postgres_inventory_chunks import (
    read_checkpoint,
    replay_resource_chunks,
)
from fdai.delivery.persistence.postgres_inventory_prepared import require_unsealed
from fdai.delivery.persistence.postgres_inventory_snapshot_support import (
    InventorySnapshotConnectionConfig,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
)


async def load_unfinished_collection(
    config: InventorySnapshotConnectionConfig, manifest: InventoryCoverageManifest
) -> ResumedInventoryCollection | None:
    """Never use retained continuation tokens as evidence of provider snapshot consistency."""
    context = collection_context_digest(manifest)
    async with (
        asyncio.timeout(30),
        await psycopg.AsyncConnection.connect(
            config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
        ) as connection,
    ):
        await connection.execute(
            "SELECT set_config('statement_timeout',%s,true)", (str(config.statement_timeout_ms),)
        )
        cursor = await connection.execute(
            "SELECT candidate.*, checkpoint.key AS checkpoint_key "
            "FROM inventory_snapshot candidate "
            "JOIN state_kv checkpoint ON checkpoint.value->>'attempt_id'=candidate.id "
            "AND starts_with(checkpoint.key,'inventory-collection:') "
            "AND right(checkpoint.key,11)=':checkpoint' "
            "WHERE candidate.status='collecting' AND checkpoint.value->>'context_digest'=%s "
            "AND candidate.started_at BETWEEN NOW()-INTERVAL '30 minutes' AND NOW() "
            "ORDER BY candidate.started_at DESC,candidate.id LIMIT 2 FOR UPDATE OF candidate",
            (context,),
        )
        candidates = await cursor.fetchall()
        if not candidates:
            return None
        if len(candidates) != 1:
            raise ValueError("inventory unfinished collection is ambiguous")
        candidate = candidates[0]
        attempt = candidate["id"]
        if candidate["checkpoint_key"] != collection_key(attempt) + ":checkpoint":
            raise ValueError("inventory unfinished checkpoint identity changed")
        await require_unsealed(connection, attempt)
        original = InventoryCoverageManifest(
            source=candidate["source"],
            scopes=tuple(candidate["scopes"]),
            resource_types=tuple(candidate["resource_types"]),
            metadata=candidate["metadata"],
            started_at=candidate["started_at"],
            observation_kind=InventoryObservationKind(candidate["observation_kind"]),
        )
        if collection_context_digest(original) != context:
            raise ValueError("inventory unfinished source context changed")
        checkpoint = await read_checkpoint(connection, attempt_id=attempt, context_digest=context)
        if checkpoint is None:
            raise ValueError("inventory unfinished checkpoint is unavailable")
        resources = {}
        async for batch in replay_resource_chunks(
            connection, attempt_id=attempt, context_digest=context, checkpoint=checkpoint
        ):
            cursor = await connection.execute(
                "SELECT resource_id,resource_type,props,provider_ref,last_seen "
                "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                "AND resource_id=ANY(%s::text[])",
                (attempt, [resource.resource_id for resource in batch.resources]),
            )
            rows = {row["resource_id"]: row for row in await cursor.fetchall()}
            for resource in batch.resources:
                if resource.resource_id in resources:
                    raise ValueError("inventory unfinished prefix has duplicate identities")
                row = rows.get(resource.resource_id)
                observed_at = (
                    datetime.fromisoformat(resource.last_seen.replace("Z", "+00:00"))
                    if resource.last_seen
                    else None
                )
                if row is None or (
                    row["resource_type"],
                    row["props"],
                    row["provider_ref"],
                    row["last_seen"],
                ) != (resource.type, resource.props, resource.provider_ref, observed_at):
                    raise ValueError("inventory unfinished candidate differs from its chunks")
                resources[resource.resource_id] = resource
        cursor = await connection.execute(
            "SELECT count(*) AS count FROM inventory_snapshot_resource WHERE snapshot_id=%s",
            (attempt,),
        )
        row = await cursor.fetchone()
        if row is None or row["count"] != len(resources):
            raise ValueError("inventory unfinished candidate has uncheckpointed resources")
        cursor = await connection.execute(
            "SELECT count(*) AS count FROM inventory_snapshot_link WHERE snapshot_id=%s", (attempt,)
        )
        row = await cursor.fetchone()
        if row is None or row["count"] != 0:
            raise ValueError("inventory unfinished candidate reached unsealed enrichment")
        return ResumedInventoryCollection(attempt, original, checkpoint, resources)
