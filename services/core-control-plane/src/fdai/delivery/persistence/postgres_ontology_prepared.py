"""Immutable ontology replacement inputs; preparation never changes active graph rows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.persistence.postgres_ontology_partitions import prepare_partition_set
from fdai.shared.contracts.models import OntologyTypeRef
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    canonical_json_mapping,
)

_MAX_CHUNK_BYTES = 1024 * 1024
_MAX_GRAPH_BYTES = 32 * 1024 * 1024
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PREFIX = "ontology-prepared:"

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStoreConfig


def _encode(value: Mapping[str, Any], *, limit: int) -> str:
    encoded = canonical_json_mapping(value, path="prepared_ontology")[1]
    if len(encoded.encode()) > limit:
        raise OntologyInstanceValidationError("prepared ontology content exceeds its byte bound")
    return encoded


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedOntologyReplacement:
    """Frozen canonical inputs, not a verification verdict or publication receipt."""

    manifest: str
    chunks: tuple[str, ...]

    @property
    def digest(self) -> str:
        return _digest(self.manifest)


def prepare_replacement(
    *,
    objects: Sequence[OntologyObjectRecord],
    links: Sequence[OntologyLinkRecord],
    previous_object_ids: Sequence[str],
    previous_link_keys: Sequence[tuple[str, str, str]],
    release_digest: str,
    expected_active_generation: str,
    state_updates: Mapping[str, Mapping[str, Any]],
    observation_projection_watermark: int | None,
) -> PreparedOntologyReplacement:
    """Freeze normalized, release-pinned inputs before any asynchronous storage operation."""
    if (
        _DIGEST.fullmatch(release_digest) is None
        or not expected_active_generation.strip()
        or len(expected_active_generation) > 256
        or len(objects) > 50_000
        or len(links) > 200_000
        or len(previous_object_ids) > 50_000
        or len(previous_link_keys) > 200_000
        or len({record.id for record in objects}) != len(objects)
        or len({(record.from_id, record.link_type, record.to_id) for record in links}) != len(links)
        or (
            observation_projection_watermark is not None
            and (
                type(observation_projection_watermark) is not int
                or observation_projection_watermark < 0
            )
        )
    ):
        raise OntologyInstanceValidationError(
            "prepared ontology identity or record bound is invalid"
        )
    chunks: list[str] = []
    total_bytes = 0
    ordered_objects = sorted(objects, key=lambda record: record.id)
    ordered_links = sorted(
        links, key=lambda record: (record.from_id, record.link_type, record.to_id)
    )
    for kind, records in (("objects", ordered_objects), ("links", ordered_links)):
        pending: list[str] = []
        pending_bytes = 0
        for record in records:
            reference = record.type_ref
            if reference is None or reference.catalog_digest != release_digest:
                raise OntologyInstanceValidationError("prepared ontology record release changed")
            content: dict[str, Any] = {
                "properties": record.properties,
                "type_ref": reference.model_dump(mode="json"),
            }
            if isinstance(record, OntologyObjectRecord):
                content.update(
                    id=record.id, object_type=record.object_type, revision=record.revision
                )
            else:
                content.update(
                    from_id=record.from_id, to_id=record.to_id, link_type=record.link_type
                )
            encoded = _encode(content, limit=_MAX_CHUNK_BYTES - 128)
            size = len(encoded.encode()) + 1
            if pending and (len(pending) >= 1000 or pending_bytes + size > _MAX_CHUNK_BYTES - 128):
                chunk = _encode(
                    {"kind": kind, "records": [json.loads(item) for item in pending]},
                    limit=_MAX_CHUNK_BYTES,
                )
                chunks.append(chunk)
                total_bytes += len(chunk.encode())
                pending = []
                pending_bytes = 0
            pending.append(encoded)
            pending_bytes += size
            if total_bytes + pending_bytes > _MAX_GRAPH_BYTES:
                raise OntologyInstanceValidationError(
                    "prepared ontology graph exceeds its byte bound"
                )
        if pending:
            chunk = _encode(
                {"kind": kind, "records": [json.loads(item) for item in pending]},
                limit=_MAX_CHUNK_BYTES,
            )
            chunks.append(chunk)
            total_bytes += len(chunk.encode())
    if total_bytes > _MAX_GRAPH_BYTES:
        raise OntologyInstanceValidationError("prepared ontology graph exceeds its byte bound")
    manifest = _encode(
        {
            "schema_version": "1.0.0",
            "release_digest": release_digest,
            "expected_active_generation": expected_active_generation,
            "previous_object_ids": sorted(previous_object_ids),
            "previous_link_keys": sorted(previous_link_keys),
            "object_count": len(objects),
            "link_count": len(links),
            "chunks": [_digest(chunk) for chunk in chunks],
            "partition_set": prepare_partition_set(chunks),
            "state_updates": state_updates,
            "dependency_revisions": {},
            "ownership_digest": None,
            "observation_projection_watermark": observation_projection_watermark,
        },
        limit=_MAX_MANIFEST_BYTES,
    )
    return PreparedOntologyReplacement(manifest, tuple(chunks))


def restore_replacement(
    prepared: PreparedOntologyReplacement,
    *,
    expected_digest: str,
) -> tuple[dict[str, Any], tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...]]:
    """Reconstruct exact typed input only after every content-addressed chunk verifies."""
    if prepared.digest != expected_digest:
        raise OntologyInstanceValidationError("prepared ontology manifest digest changed")
    manifest = json.loads(prepared.manifest)
    if manifest["schema_version"] != "1.0.0" or manifest["chunks"] != [
        _digest(chunk) for chunk in prepared.chunks
    ]:
        raise OntologyInstanceValidationError("prepared ontology chunk manifest changed")
    if "partition_set" in manifest and manifest["partition_set"] != prepare_partition_set(
        prepared.chunks
    ):
        raise OntologyInstanceValidationError("prepared ontology partition set changed")
    objects = []
    links = []
    for chunk in prepared.chunks:
        payload = json.loads(chunk)
        for values in payload["records"]:
            values["type_ref"] = OntologyTypeRef.model_validate(values["type_ref"])
            if payload["kind"] == "objects":
                objects.append(OntologyObjectRecord(**values))
            elif payload["kind"] == "links":
                links.append(OntologyLinkRecord(**values))
            else:
                raise OntologyInstanceValidationError("prepared ontology chunk kind is invalid")
    if len(objects) != manifest["object_count"] or len(links) != manifest["link_count"]:
        raise OntologyInstanceValidationError("prepared ontology record count changed")
    return manifest, tuple(objects), tuple(links)


async def _dependency_revisions(
    connection: psycopg.AsyncConnection[Any], identifiers: Sequence[str], *, lock: bool
) -> dict[str, Any]:
    retained: dict[str, Any] = dict.fromkeys(identifiers)
    for offset in range(0, len(identifiers), 1000):
        query = (
            "SELECT id, revision, object_type, type_version, catalog_digest, properties "
            "FROM ontology_resource "
            "WHERE id=ANY(%s::text[]) ORDER BY id"
        )
        cursor = await connection.execute(
            query + (" FOR SHARE" if lock else ""), (list(identifiers[offset : offset + 1000]),)
        )
        for row in await cursor.fetchall():
            retained[row["id"]] = {key: value for key, value in row.items() if key != "id"}
    return retained


async def pin_replacement_dependencies(
    config: PostgresOntologyInstanceStoreConfig, prepared: PreparedOntologyReplacement
) -> PreparedOntologyReplacement:
    """Bind removed and external endpoint revisions from one read-only database snapshot."""
    manifest, objects, links = restore_replacement(prepared, expected_digest=prepared.digest)
    desired = {record.id for record in objects}
    foreign = {identifier for link in links for identifier in (link.from_id, link.to_id)} - desired
    identifiers = sorted(foreign | (set(manifest["previous_object_ids"]) - desired))
    if len(identifiers) > 250_000:
        raise OntologyInstanceValidationError("prepared ontology dependencies exceed their bound")
    desired_ownership = manifest["state_updates"].get("inventory-ontology:manifest")
    ownership_bound = isinstance(desired_ownership, dict) and "object_ids" in desired_ownership
    if not identifiers and not ownership_bound:
        return prepared
    async with (
        asyncio.timeout(30),
        await psycopg.AsyncConnection.connect(
            config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
        ) as connection,
    ):
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)", (str(config.statement_timeout_ms),)
        )
        revisions = await _dependency_revisions(connection, identifiers, lock=False)
        if ownership_bound:
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
            )
            row = await cursor.fetchone()
            prior = row["value"] if row is not None else {"object_ids": [], "link_keys": []}
            if not isinstance(prior, dict) or (
                "object_ids" not in prior
                or "link_keys" not in prior
                or sorted(prior.get("object_ids", [])) != sorted(manifest["previous_object_ids"])
                or sorted(prior.get("link_keys", [])) != sorted(manifest["previous_link_keys"])
                or sorted(desired_ownership["object_ids"]) != sorted(desired)
                or sorted(desired_ownership.get("link_keys", []))
                != sorted([record.from_id, record.link_type, record.to_id] for record in links)
            ):
                raise OntologyInstanceValidationError("prepared ontology ownership set changed")
            newly_claimed = await _dependency_revisions(
                connection, sorted(desired - set(prior["object_ids"])), lock=False
            )
            if any(value is not None for value in newly_claimed.values()):
                raise OntologyInstanceValidationError(
                    "prepared ontology ownership collides with existing objects"
                )
            manifest["ownership_digest"] = _digest(
                _encode({"present": row is not None, "manifest": prior}, limit=_MAX_MANIFEST_BYTES)
            )
    if any(revisions[identifier] is None for identifier in foreign):
        raise OntologyInstanceValidationError("prepared ontology external endpoint is missing")
    manifest["dependency_revisions"] = revisions
    manifest["previous_object_ids"] = [
        identifier
        for identifier in manifest["previous_object_ids"]
        if identifier not in revisions or revisions[identifier] is not None
    ]
    return replace(prepared, manifest=_encode(manifest, limit=_MAX_MANIFEST_BYTES))


async def verify_replacement_dependencies(
    connection: psycopg.AsyncConnection[Any], manifest: Mapping[str, Any]
) -> None:
    """Hold observed dependency rows through publication; missing prior rows are never deleted."""
    expected = manifest["dependency_revisions"]
    actual = await _dependency_revisions(connection, sorted(expected), lock=True)
    if _encode(actual, limit=_MAX_MANIFEST_BYTES) != _encode(expected, limit=_MAX_MANIFEST_BYTES):
        raise OntologyInstanceValidationError("prepared ontology dependency revision changed")
    if manifest.get("ownership_digest") is not None:
        cursor = await connection.execute(
            "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest' FOR SHARE"
        )
        row = await cursor.fetchone()
        prior = row["value"] if row is not None else {"object_ids": [], "link_keys": []}
        actual_digest = _digest(
            _encode({"present": row is not None, "manifest": prior}, limit=_MAX_MANIFEST_BYTES)
        )
        if actual_digest != manifest["ownership_digest"]:
            raise OntologyInstanceValidationError("prepared ontology ownership manifest changed")


async def persist_replacement(
    config: PostgresOntologyInstanceStoreConfig, prepared: PreparedOntologyReplacement
) -> None:
    """Commit immutable private inputs before publication; conflicts never overwrite content."""
    restore_replacement(prepared, expected_digest=prepared.digest)
    content = {_PREFIX + _digest(chunk): chunk for chunk in prepared.chunks}
    content[_PREFIX + prepared.digest] = prepared.manifest
    async with (
        asyncio.timeout(30),
        await psycopg.AsyncConnection.connect(
            config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
        ) as connection,
    ):
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)", (str(config.statement_timeout_ms),)
        )
        cursor = connection.cursor()
        await cursor.executemany(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            [(key, Jsonb(json.loads(value))) for key, value in sorted(content.items())],
        )
        cursor = await connection.execute(
            "SELECT key, value FROM state_kv WHERE key=ANY(%s::text[])", (list(content),)
        )
        retained = await cursor.fetchall()
        if len(retained) != len(content) or any(
            _encode(row["value"], limit=_MAX_MANIFEST_BYTES) != content[row["key"]]
            for row in retained
        ):
            raise OntologyInstanceValidationError("prepared ontology immutable content conflicts")


async def verify_replacement_content(
    connection: psycopg.AsyncConnection[Any],
    prepared: PreparedOntologyReplacement,
) -> None:
    """Lock exact durable inputs without transferring and decoding the graph under writer lock."""
    content = {_PREFIX + _digest(chunk): chunk for chunk in prepared.chunks}
    content[_PREFIX + prepared.digest] = prepared.manifest
    keys = sorted(content)
    cursor = await connection.execute(
        "SELECT stored.key FROM state_kv stored "
        "JOIN unnest(%s::text[], %s::text[]) AS expected(key, encoded) "
        "ON stored.key=expected.key "
        "WHERE stored.value::text=(expected.encoded::jsonb)::text "
        "ORDER BY stored.key FOR SHARE OF stored",
        (keys, [content[key] for key in keys]),
    )
    if [row["key"] for row in await cursor.fetchall()] != keys:
        raise OntologyInstanceValidationError(
            "prepared ontology durable content changed or is missing"
        )


async def load_replacement(
    connection: psycopg.AsyncConnection[Any], *, expected_digest: str
) -> tuple[dict[str, Any], tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...]]:
    """Verify durable inputs under the caller's publication transaction and row locks."""
    if _DIGEST.fullmatch(expected_digest) is None:
        raise OntologyInstanceValidationError("prepared ontology digest is invalid")
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s FOR SHARE", (_PREFIX + expected_digest,)
    )
    row = await cursor.fetchone()
    if row is None:
        raise OntologyInstanceValidationError("prepared ontology manifest is missing")
    manifest = _encode(row["value"], limit=_MAX_MANIFEST_BYTES)
    if _digest(manifest) != expected_digest:
        raise OntologyInstanceValidationError("prepared ontology manifest digest changed")
    chunk_digests = row["value"].get("chunks")
    if (
        not isinstance(chunk_digests, list)
        or len(chunk_digests) > 1000
        or any(
            not isinstance(item, str) or _DIGEST.fullmatch(item) is None for item in chunk_digests
        )
    ):
        raise OntologyInstanceValidationError("prepared ontology chunk references are invalid")
    cursor = await connection.execute(
        "SELECT key, value FROM state_kv WHERE key=ANY(%s::text[]) ORDER BY key FOR SHARE",
        ([_PREFIX + item for item in chunk_digests],),
    )
    rows = {
        row["key"]: _encode(row["value"], limit=_MAX_CHUNK_BYTES) for row in await cursor.fetchall()
    }
    if len(rows) != len(chunk_digests):
        raise OntologyInstanceValidationError("prepared ontology chunks are missing or duplicated")
    prepared = PreparedOntologyReplacement(
        manifest, tuple(rows[_PREFIX + item] for item in chunk_digests)
    )
    if sum(len(chunk.encode()) for chunk in prepared.chunks) > _MAX_GRAPH_BYTES:
        raise OntologyInstanceValidationError("prepared ontology graph exceeds its byte bound")
    return restore_replacement(prepared, expected_digest=expected_digest)
