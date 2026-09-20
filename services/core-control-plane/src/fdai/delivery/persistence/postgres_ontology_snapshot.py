"""Content-addressed publication receipts for version-pinned inventory graph reads.

The existing graph writer commits these receipts in its graph/state transaction.
Prepared inputs alone are never published snapshots. Existing tables and N-1 writers
retain their contracts; this additive read boundary grants no write authority.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.persistence.postgres_ontology_prepared import (
    PreparedOntologyReplacement,
    _digest,
    _encode,
)
from fdai.delivery.persistence.postgres_ontology_source_coverage import (
    resource_graph_source_coverage,
)
from fdai.shared.contracts.models import OntologyTypeRef
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStoreConfig

_PREFIX = "ontology-committed:"
_MAX_RECEIPT_BYTES = 8 * 1024 * 1024
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


@dataclass(frozen=True, slots=True)
class CommittedOntologyPage:
    """One page of the published owner's subgraph, not other owners' endpoint contents."""

    snapshot_digest: str
    generation: str
    release_digest: str
    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]
    next_cursor: str | None
    total_count: int


async def record_committed_snapshot(
    connection: psycopg.AsyncConnection[Any],
    prepared: PreparedOntologyReplacement,
    committed_revisions: Mapping[str, int],
    state_updates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """Record actual committed revisions inside the caller's existing graph transaction."""
    manifest = json.loads(prepared.manifest)
    if len(committed_revisions) != manifest["object_count"] or any(
        type(value) is not int or value < 1 for value in committed_revisions.values()
    ):
        raise OntologyInstanceValidationError("committed ontology revisions are invalid")
    encoded = _encode(
        {
            "schema_version": "1.0.0",
            "prepared_digest": prepared.digest,
            "generation": manifest["expected_active_generation"],
            "release_digest": manifest["release_digest"],
            "object_revisions": committed_revisions,
            "partitions": [
                {
                    "digest": _digest(chunk),
                    "kind": (payload := json.loads(chunk))["kind"],
                    "count": len(payload["records"]),
                }
                for chunk in prepared.chunks
            ],
        },
        limit=_MAX_RECEIPT_BYTES,
    )
    digest = _digest(encoded)
    key = _PREFIX + digest
    await connection.execute(
        "INSERT INTO state_kv (key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING",
        (key, Jsonb(json.loads(encoded))),
    )
    cursor = await connection.execute("SELECT value FROM state_kv WHERE key=%s FOR SHARE", (key,))
    row = await cursor.fetchone()
    if row is None or _encode(row["value"], limit=_MAX_RECEIPT_BYTES) != encoded:
        raise OntologyInstanceValidationError("committed ontology receipt conflicts with content")
    return {
        **state_updates,
        "inventory-ontology:prepared-snapshot": {
            **state_updates["inventory-ontology:prepared-snapshot"],
            "snapshot_digest": digest,
        },
    }


@asynccontextmanager
async def _snapshot_connection(
    config: PostgresOntologyInstanceStoreConfig,
    connection: psycopg.AsyncConnection[Any] | None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    if connection is not None:
        yield connection
        return
    async with await psycopg.AsyncConnection.connect(
        config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
    ) as opened:
        await opened.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        await opened.execute(
            "SELECT set_config('statement_timeout',%s,true)", (str(config.statement_timeout_ms),)
        )
        yield opened


async def pin_current_snapshot(
    config: PostgresOntologyInstanceStoreConfig,
    *,
    _connection: psycopg.AsyncConnection[Any] | None = None,
) -> str | None:
    """Select a committed inventory version only when graph and inventory generations agree."""
    async with (
        asyncio.timeout(10),
        _snapshot_connection(config, _connection) as connection,
    ):
        cursor = await connection.execute(
            "SELECT pointer.value, active.snapshot_id FROM state_kv pointer "
            "LEFT JOIN inventory_active active ON active.singleton=TRUE "
            "WHERE pointer.key='inventory-ontology:prepared-snapshot'",
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        pointer = row["value"]
        if (
            not isinstance(pointer, Mapping)
            or pointer.get("generation") != row["snapshot_id"]
            or not isinstance(pointer.get("snapshot_digest"), str)
            or _DIGEST.fullmatch(pointer["snapshot_digest"]) is None
        ):
            raise OntologyInstanceValidationError(
                "committed ontology snapshot is unavailable or pending"
            )
        receipt = await _read_content(
            connection, _PREFIX, pointer["snapshot_digest"], _MAX_RECEIPT_BYTES
        )
        if (
            receipt.get("prepared_digest") != pointer.get("digest")
            or receipt.get("generation") != pointer.get("generation")
            or receipt.get("release_digest") != pointer.get("release_digest")
        ):
            raise OntologyInstanceValidationError(
                "committed ontology snapshot pointer is inconsistent"
            )
        return str(pointer["snapshot_digest"])


async def _read_content(
    connection: psycopg.AsyncConnection[Any],
    prefix: str,
    digest: object,
    limit: int,
) -> dict[str, Any]:
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise OntologyInstanceValidationError("committed ontology content reference is invalid")
    cursor = await connection.execute("SELECT value FROM state_kv WHERE key=%s", (prefix + digest,))
    row = await cursor.fetchone()
    if row is None or not isinstance(row["value"], dict):
        raise OntologyInstanceValidationError("committed ontology content is unavailable")
    if _digest(_encode(row["value"], limit=limit)) != digest:
        raise OntologyInstanceValidationError("committed ontology content digest changed")
    return dict(row["value"])


async def read_snapshot_page(
    config: PostgresOntologyInstanceStoreConfig,
    *,
    snapshot_digest: str,
    kind: Literal["objects", "links"] = "objects",
    cursor: str | None = None,
    limit: int = 1000,
    _connection: psycopg.AsyncConnection[Any] | None = None,
    _index: _SnapshotIndex | None = None,
) -> CommittedOntologyPage:
    """Read immutable committed partitions; a cursor selects content and grants no authorization.

    Callers must retain their existing principal/scope checks. An absent receipt (including
    after a database rebuild) fails closed, never falls back to current live graph rows.
    """
    if (
        not isinstance(snapshot_digest, str)
        or _DIGEST.fullmatch(snapshot_digest) is None
        or kind not in {"objects", "links"}
        or type(limit) is not int
        or not 1 <= limit <= 1000
    ):
        raise ValueError("snapshot page requires a valid digest, kind and bounded limit")
    offset = 0
    if cursor is not None:
        prefix = snapshot_digest + ":" + kind + ":"
        if (
            not isinstance(cursor, str)
            or not cursor.startswith(prefix)
            or re.fullmatch(r"0|[1-9][0-9]{0,5}", cursor[len(prefix) :]) is None
        ):
            raise ValueError("snapshot page cursor does not match its version and kind")
        offset = int(cursor[len(prefix) :])
    async with (
        asyncio.timeout(30),
        _snapshot_connection(config, _connection) as connection,
    ):
        index = _index or await _read_index(connection, snapshot_digest)
        if index.connection is not connection or index.digest != snapshot_digest:
            raise OntologyInstanceValidationError(
                "committed ontology snapshot index belongs to another read"
            )
        receipt, partitions, revisions = index.receipt, index.partitions, index.revisions
        total = sum(part["count"] for part in partitions if part["kind"] == kind)
        if offset > total:
            raise ValueError("snapshot page cursor is beyond the recorded bounds")
        objects = []
        links = []
        consumed = 0
        selected = 0
        for partition in partitions:
            if partition["kind"] != kind:
                continue
            start = consumed
            consumed += partition["count"]
            if consumed <= offset:
                continue
            if selected >= limit:
                break
            chunk = await _read_content(
                connection, "ontology-prepared:", partition["digest"], 1024 * 1024
            )
            records = chunk.get("records")
            if (
                chunk.get("kind") != kind
                or not isinstance(records, list)
                or len(records) != partition["count"]
            ):
                raise OntologyInstanceValidationError(
                    "committed ontology snapshot partition changed"
                )
            for values in records[
                max(0, offset - start) : max(0, offset - start) + limit - selected
            ]:
                values = dict(values)
                values["type_ref"] = OntologyTypeRef.model_validate(values["type_ref"])
                if values["type_ref"].catalog_digest != receipt["release_digest"]:
                    raise OntologyInstanceValidationError(
                        "committed ontology snapshot release changed"
                    )
                if kind == "objects":
                    if values.get("id") not in revisions or revisions[values["id"]] not in {
                        values["revision"],
                        values["revision"] + 1,
                    }:
                        raise OntologyInstanceValidationError(
                            "committed ontology snapshot revision changed"
                        )
                    objects.append(
                        OntologyObjectRecord(**{**values, "revision": revisions[values["id"]]})
                    )
                else:
                    links.append(OntologyLinkRecord(**values))
                selected += 1
        next_offset = offset + selected
        return CommittedOntologyPage(
            snapshot_digest=snapshot_digest,
            generation=receipt["generation"],
            release_digest=receipt["release_digest"],
            objects=tuple(objects),
            links=tuple(links),
            total_count=total,
            next_cursor=f"{snapshot_digest}:{kind}:{next_offset}" if next_offset < total else None,
        )


@dataclass(frozen=True, slots=True)
class _SnapshotIndex:
    connection: psycopg.AsyncConnection[Any]
    digest: str
    receipt: dict[str, Any]
    manifest: dict[str, Any]
    partitions: tuple[dict[str, Any], ...]
    revisions: dict[str, int]


async def _read_index(connection: psycopg.AsyncConnection[Any], digest: str) -> _SnapshotIndex:
    receipt = await _read_content(connection, _PREFIX, digest, _MAX_RECEIPT_BYTES)
    manifest = await _read_content(
        connection, "ontology-prepared:", receipt.get("prepared_digest"), 32 * 1024 * 1024
    )
    partitions = receipt.get("partitions")
    revisions = receipt.get("object_revisions")
    if (
        receipt.get("schema_version") != "1.0.0"
        or manifest.get("schema_version") != "1.0.0"
        or receipt.get("generation") != manifest.get("expected_active_generation")
        or receipt.get("release_digest") != manifest.get("release_digest")
        or not isinstance(partitions, list)
        or len(partitions) > 1000
        or not isinstance(revisions, dict)
        or len(revisions) != manifest.get("object_count")
        or any(type(value) is not int or value < 1 for value in revisions.values())
        or any(
            not isinstance(part, dict)
            or set(part) != {"digest", "kind", "count"}
            or part["kind"] not in {"objects", "links"}
            or type(part["count"]) is not int
            or not 1 <= part["count"] <= 1000
            for part in partitions
        )
        or [part["digest"] for part in partitions] != manifest.get("chunks")
        or sum(part["count"] for part in partitions if part["kind"] == "objects")
        != manifest.get("object_count")
        or sum(part["count"] for part in partitions if part["kind"] == "links")
        != manifest.get("link_count")
    ):
        raise OntologyInstanceValidationError("committed ontology snapshot receipt is malformed")
    return _SnapshotIndex(connection, digest, receipt, manifest, tuple(partitions), revisions)


async def scan_current_inventory_snapshot(
    connection: psycopg.AsyncConnection[Any],
    config: PostgresOntologyInstanceStoreConfig,
    candidate_limit: int,
) -> OntologyGraphSnapshot | None:
    """Reuse a caller-owned read snapshot; only legacy current scans may use live rows."""
    async with asyncio.timeout(30):
        cursor = await connection.execute(
            "SELECT value FROM state_kv WHERE key='inventory-ontology:prepared-snapshot'"
        )
        row = await cursor.fetchone()
        if row is None or (
            isinstance(row["value"], dict)
            and set(row["value"]) == {"schema_version", "digest", "generation", "release_digest"}
            and row["value"]["schema_version"] == "1.0.0"
            and all(isinstance(value, str) and value for value in row["value"].values())
            and _DIGEST.fullmatch(row["value"]["digest"]) is not None
            and _DIGEST.fullmatch(row["value"]["release_digest"]) is not None
        ):
            return None
        digest = await pin_current_snapshot(config, _connection=connection)
        if digest is None:
            raise OntologyInstanceValidationError("committed ontology snapshot is unavailable")
        index = await _read_index(connection, digest)
        receipt, manifest = index.receipt, index.manifest
        updates = manifest.get("state_updates")
        keys = ("inventory-ontology:manifest", "inventory-ontology:status")
        cursor = await connection.execute(
            "SELECT key,value FROM state_kv WHERE key=ANY(%s::text[])", (list(keys),)
        )
        current = {row["key"]: row["value"] for row in await cursor.fetchall()}
        if not isinstance(updates, dict) or any(
            key not in updates or key not in current or updates[key] != current[key] for key in keys
        ):
            raise OntologyInstanceValidationError("committed ontology snapshot markers changed")
        complete, generation = await resource_graph_source_coverage(
            connection, (), requires_resource_coverage=True, expresses_relationships=False
        )
        if not complete or generation != receipt.get("generation"):
            return OntologyGraphSnapshot(source_complete=False, source_generation=generation)
        cursor = await connection.execute(
            "SELECT id,revision,type_version,catalog_digest FROM ontology_resource "
            "WHERE object_type='Resource' ORDER BY id LIMIT 50001"
        )
        rows = await cursor.fetchall()
        if (
            len(rows) > 50000
            or {row["id"]: row["revision"] for row in rows} != receipt.get("object_revisions")
            or any(row["catalog_digest"] != receipt.get("release_digest") for row in rows)
        ):
            raise OntologyInstanceValidationError(
                "committed ontology snapshot live revisions changed"
            )
        objects: list[OntologyObjectRecord] = []
        versions = {row["id"]: row["type_version"] for row in rows}
        next_cursor = None
        while True:
            page = await read_snapshot_page(
                config,
                snapshot_digest=digest,
                cursor=next_cursor,
                limit=min(1000, candidate_limit - len(objects)),
                _connection=connection,
                _index=index,
            )
            if any(
                record.object_type != "Resource"
                or record.type_ref is None
                or record.type_ref.version != versions.get(record.id)
                for record in page.objects
            ):
                raise OntologyInstanceValidationError(
                    "committed ontology snapshot owner type changed"
                )
            objects.extend(page.objects)
            next_cursor = page.next_cursor
            if next_cursor is None or len(objects) == candidate_limit:
                break
        return OntologyGraphSnapshot(
            objects=tuple(objects),
            truncated=next_cursor is not None,
            source_complete=True,
            source_generation=generation,
        )
