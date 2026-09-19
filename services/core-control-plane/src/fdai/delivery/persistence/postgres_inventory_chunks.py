"""Immutable bounded resource chunks and checkpoints in the snapshot transaction."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.inventory_collection import (
    MAX_COLLECTION_BYTES,
    MAX_COLLECTION_CHUNKS,
    collection_key,
)
from fdai.delivery.inventory_collection import (
    collection_context_digest as collection_context_digest,
)
from fdai.delivery.inventory_collection import (
    resource_chunk as resource_chunk,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_support import (
    InventorySnapshotConnectionConfig,
)
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
)


async def require_collection_context(
    connection: psycopg.AsyncConnection[Any],
    attempt_id: str,
    digest: str,
) -> None:
    cursor = await connection.execute(
        "SELECT source, scopes, resource_types, observation_kind, metadata "
        "FROM inventory_snapshot WHERE id=%s "
        "AND started_at >= NOW() - INTERVAL '30 minutes' AND started_at <= NOW()",
        (attempt_id,),
    )
    row = await cursor.fetchone()
    if (
        row is None
        or collection_context_digest(
            InventoryCoverageManifest(
                source=row["source"],
                scopes=tuple(row["scopes"]),
                resource_types=tuple(row["resource_types"]),
                observation_kind=InventoryObservationKind(row["observation_kind"]),
                metadata=row["metadata"],
            )
        )
        != digest
    ):
        raise ValueError("inventory collection context changed or attempt expired")


async def commit_resource_chunk(
    connection: psycopg.AsyncConnection[Any],
    *,
    chunk: Mapping[str, Any],
    write_resources: Callable[[], Awaitable[None]],
) -> Mapping[str, Any]:
    """The caller holds the collecting-attempt row lock and owns transaction rollback."""
    key = collection_key(chunk["attempt_id"])
    chunk_key = f"{key}:chunk:{chunk['sequence']:08d}"
    cursor = await connection.execute("SELECT value FROM state_kv WHERE key=%s", (chunk_key,))
    retained = await cursor.fetchone()
    if retained is not None:
        if json.dumps(retained["value"], sort_keys=True) != json.dumps(chunk, sort_keys=True):
            raise ValueError("inventory chunk identity already has different content")
        checkpoint = await read_checkpoint(
            connection,
            attempt_id=chunk["attempt_id"],
            context_digest=chunk["context_digest"],
        )
        if checkpoint is None or checkpoint["next_sequence"] <= chunk["sequence"]:
            raise ValueError("inventory duplicate chunk has no durable checkpoint")
        return chunk
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s", (key + ":checkpoint",)
    )
    row = await cursor.fetchone()
    checkpoint = row["value"] if row is not None else None
    byte_count = len(json.dumps(chunk, sort_keys=True, separators=(",", ":")).encode())
    resource_count = len(chunk["resources"])
    if checkpoint is None:
        if chunk["sequence"] != 0:
            raise ValueError("inventory chunk has no initial checkpoint")
    elif (
        not isinstance(checkpoint, Mapping)
        or set(checkpoint)
        != {
            "schema_version",
            "attempt_id",
            "context_digest",
            "next_sequence",
            "digest",
            "cursor",
            "byte_count",
            "resource_count",
        }
        or type(checkpoint.get("next_sequence")) is not int
        or checkpoint.get("context_digest") != chunk["context_digest"]
        or checkpoint.get("next_sequence") != chunk["sequence"]
        or checkpoint.get("digest") != chunk["previous_digest"]
    ):
        raise ValueError("inventory chunk checkpoint fence changed")
    if checkpoint is not None:
        for name in ("byte_count", "resource_count"):
            if type(checkpoint.get(name)) is not int or checkpoint[name] < 0:
                raise ValueError("inventory chunk checkpoint counters are invalid")
        byte_count += checkpoint["byte_count"]
        resource_count += checkpoint["resource_count"]
    if byte_count > MAX_COLLECTION_BYTES or resource_count > 50000:
        raise ValueError("inventory chunk collection exceeds its capacity")
    await write_resources()
    await connection.execute(
        "INSERT INTO state_kv (key, value) VALUES (%s, %s)", (chunk_key, Jsonb(chunk))
    )
    checkpoint = {
        "schema_version": "1.0.0",
        "attempt_id": chunk["attempt_id"],
        "context_digest": chunk["context_digest"],
        "next_sequence": chunk["sequence"] + 1,
        "digest": chunk["digest"],
        "cursor": chunk["cursor"],
        "byte_count": byte_count,
        "resource_count": resource_count,
    }
    await connection.execute(
        "INSERT INTO state_kv (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
        (key + ":checkpoint", Jsonb(checkpoint)),
    )
    return chunk


async def read_checkpoint(
    connection: psycopg.AsyncConnection[Any],
    *,
    attempt_id: str,
    context_digest: str,
) -> Mapping[str, Any] | None:
    key = collection_key(attempt_id)
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s", (key + ":checkpoint",)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    checkpoint = row["value"]
    if (
        not isinstance(checkpoint, Mapping)
        or checkpoint.get("schema_version") != "1.0.0"
        or checkpoint.get("attempt_id") != attempt_id
        or checkpoint.get("context_digest") != context_digest
        or type(checkpoint.get("next_sequence")) is not int
        or not 1 <= checkpoint["next_sequence"] <= MAX_COLLECTION_CHUNKS
        or type(checkpoint.get("byte_count")) is not int
        or not 0 < checkpoint["byte_count"] <= MAX_COLLECTION_BYTES
        or type(checkpoint.get("resource_count")) is not int
        or not 0 < checkpoint["resource_count"] <= 50000
    ):
        raise ValueError("inventory chunk checkpoint is invalid or belongs to another context")
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s",
        (f"{key}:chunk:{checkpoint['next_sequence'] - 1:08d}",),
    )
    row = await cursor.fetchone()
    chunk = row["value"] if row is not None else None
    if not isinstance(chunk, Mapping):
        raise ValueError("inventory checkpoint has no durable chunk")
    try:
        rebuilt = resource_chunk(
            attempt_id=attempt_id,
            context_digest=context_digest,
            sequence=checkpoint["next_sequence"] - 1,
            previous_digest=chunk["previous_digest"],
            batch=InventoryBatch(
                resources=tuple(ResourceRecord(**resource) for resource in chunk["resources"]),
                cursor=chunk["cursor"],
            ),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("inventory checkpoint chunk is malformed") from exc
    if (
        json.dumps(rebuilt, sort_keys=True) != json.dumps(chunk, sort_keys=True)
        or rebuilt["digest"] != checkpoint.get("digest")
        or rebuilt["cursor"] != checkpoint.get("cursor")
    ):
        raise ValueError("inventory checkpoint chunk content changed")
    return checkpoint


async def replay_resource_chunks(
    connection: psycopg.AsyncConnection[Any],
    *,
    attempt_id: str,
    context_digest: str,
    checkpoint: Mapping[str, Any],
) -> AsyncIterator[InventoryBatch]:
    """Replay one bounded page at a time; the caller retains the collecting-attempt lock."""
    prefix = collection_key(attempt_id)
    previous_digest = None
    total_bytes = 0
    total_resources = 0
    for sequence in range(checkpoint["next_sequence"]):
        cursor = await connection.execute(
            "SELECT value FROM state_kv WHERE key=%s",
            (f"{prefix}:chunk:{sequence:08d}",),
        )
        row = await cursor.fetchone()
        raw = row["value"] if row is not None else None
        if not isinstance(raw, Mapping):
            raise ValueError("inventory replay chunk is missing")
        try:
            batch = InventoryBatch(
                resources=tuple(ResourceRecord(**item) for item in raw["resources"]),
                cursor=raw["cursor"],
            )
            expected = resource_chunk(
                attempt_id=attempt_id,
                context_digest=context_digest,
                sequence=sequence,
                previous_digest=previous_digest,
                batch=batch,
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("inventory replay chunk is malformed") from exc
        if json.dumps(raw, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError("inventory replay chunk content changed")
        previous_digest = expected["digest"]
        total_resources += len(batch.resources)
        total_bytes += len(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode())
        if total_bytes > MAX_COLLECTION_BYTES or total_resources > 50000:
            raise ValueError("inventory replay exceeds collection capacity")
        yield batch
    if (
        previous_digest != checkpoint["digest"]
        or total_bytes != checkpoint["byte_count"]
        or total_resources != checkpoint["resource_count"]
    ):
        raise ValueError("inventory replay checkpoint does not cover its chunks")


@asynccontextmanager
async def _collection_read(
    config: InventorySnapshotConnectionConfig,
    attempt_id: str,
    context_digest: str,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    async with asyncio.timeout(30):
        async with await psycopg.AsyncConnection.connect(
            config.dsn,
            row_factory=dict_row,
            connect_timeout=config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(config.statement_timeout_ms),),
                )
                cursor = await connection.execute(
                    "SELECT status FROM inventory_snapshot WHERE id=%s FOR UPDATE",
                    (attempt_id,),
                )
                row = await cursor.fetchone()
                if row is None or row["status"] != "collecting":
                    raise ValueError("inventory chunk attempt is no longer collecting")
                await require_collection_context(connection, attempt_id, context_digest)
                yield connection


async def load_checkpoint(
    config: InventorySnapshotConnectionConfig,
    attempt_id: str,
    *,
    context_digest: str,
) -> Mapping[str, Any] | None:
    async with _collection_read(config, attempt_id, context_digest) as connection:
        return await read_checkpoint(
            connection, attempt_id=attempt_id, context_digest=context_digest
        )


async def replay_snapshot_chunks(
    config: InventorySnapshotConnectionConfig,
    attempt_id: str,
    *,
    context_digest: str,
) -> AsyncIterator[InventoryBatch]:
    async with _collection_read(config, attempt_id, context_digest) as connection:
        checkpoint = await read_checkpoint(
            connection, attempt_id=attempt_id, context_digest=context_digest
        )
        if checkpoint is not None:
            async for batch in replay_resource_chunks(
                connection,
                attempt_id=attempt_id,
                context_digest=context_digest,
                checkpoint=checkpoint,
            ):
                yield batch
