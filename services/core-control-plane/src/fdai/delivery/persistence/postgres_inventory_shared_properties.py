"""Share rebuildable snapshot bodies while retaining exact per-row evidence metadata."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_inventory_shared_membership import (
    canonical_json,
    content_digest,
    inventory_storage_available,
)
from fdai.rule_catalog.schema.zstd_codec import (
    DEFAULT_ZSTD_LEVEL,
    ZstdRecordDictionary,
    decode_zstd_text_armor,
    encode_zstd_text_armor,
    train_record_dictionary,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
)

_METADATA_KEYS = (STATE_FACT_METADATA_PROPERTY, LINK_OBSERVATION_METADATA_PROPERTY)
_LOCK = "fdai.inventory.snapshot-properties"
_MAX_PROPERTY_BODY_BYTES = 1024 * 1024
_DEFAULT_MIN_COMPRESS_BYTES = 256
_RELATED = (
    "inventory_snapshot",
    "inventory_active",
    "inventory_snapshot_link",
    "inventory_snapshot_properties",
    "inventory_snapshot_resource_row",
    "inventory_snapshot_link_row",
)


def factor_properties(properties: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    body = canonical_json(
        {key: value for key, value in properties.items() if key not in _METADATA_KEYS}
    )
    freshness = {key: properties[key] for key in _METADATA_KEYS if key in properties}
    return content_digest(body), body, freshness


def train_property_body_dictionary(
    bodies: Sequence[str],
    *,
    dict_size: int = 16 * 1024,
) -> ZstdRecordDictionary:
    """Train a shared Zstandard dictionary over representative canonical JSON property bodies."""
    return train_record_dictionary(bodies, dict_size=dict_size)


def compress_property_body(
    body: str,
    *,
    dictionary: ZstdRecordDictionary | Any | None = None,
    min_compress_bytes: int = _DEFAULT_MIN_COMPRESS_BYTES,
    level: int = DEFAULT_ZSTD_LEVEL,
) -> str:
    """Compress a canonical JSON property body into a ``zstd1:`` armor string when beneficial."""
    if not isinstance(body, str) or not body:
        raise ValueError("inventory property body MUST be a non-empty string")
    raw_len = len(body.encode("utf-8"))
    if raw_len > _MAX_PROPERTY_BODY_BYTES:
        raise ValueError("inventory property body exceeds 1 MiB ceiling")
    if raw_len < min_compress_bytes:
        return body
    armored = encode_zstd_text_armor(body, level=level, dictionary=dictionary)
    return armored if len(armored.encode("ascii")) < raw_len else body


def decompress_property_body(
    stored_body: str,
    *,
    expected_digest: str | None = None,
    dictionary: ZstdRecordDictionary | Any | None = None,
) -> str:
    """Restore and SHA-256-verify a canonical JSON property body from plain or ``zstd1:`` text."""
    return decode_zstd_text_armor(
        stored_body,
        max_output_size=_MAX_PROPERTY_BODY_BYTES,
        expected_uncompressed_sha256=expected_digest,
        dictionary=dictionary,
    )


async def share_property_rows(
    connection: psycopg.AsyncConnection[Any],
    rows: list[dict[str, Any]],
    *,
    compress: bool = False,
    dictionary: ZstdRecordDictionary | Any | None = None,
) -> list[dict[str, Any]]:
    """Lock against bounded orphan collection until the caller commits its row references."""
    if not await inventory_storage_available(connection, _RELATED):
        raise ValueError(
            "shared inventory properties are unavailable in the logical inventory schema"
        )
    await connection.execute(
        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))", (_LOCK,)
    )
    bodies: dict[str, str] = {}
    shared = []
    for row in rows:
        digest, body, freshness = factor_properties(row["props"])
        bodies[digest] = compress_property_body(body, dictionary=dictionary) if compress else body
        shared.append(
            {
                **{key: value for key, value in row.items() if key != "props"},
                "props_digest": digest,
                "props_freshness": freshness,
            }
        )
    cursor = connection.cursor()
    await cursor.executemany(
        "INSERT INTO inventory_snapshot_properties (digest, body) VALUES (%s, %s) "
        "ON CONFLICT (digest) DO NOTHING",
        sorted(bodies.items()),
    )
    return shared


async def prune_shared_properties(
    connection: psycopg.AsyncConnection[Any],
    *,
    limit: int = 1000,
    max_bytes: int = 16 * 1024 * 1024,
) -> int:
    """Reclaim only unreferenced staging bodies under the exclusive writer fence.

    SELECT row locks would require UPDATE privilege on immutable bodies. The advisory
    fence and foreign keys already protect references; DELETE takes its own row locks.
    """
    if not 1 <= limit <= 1000 or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise ValueError("inventory property cleanup exceeds its bound")
    if not await inventory_storage_available(connection, _RELATED):
        return 0
    lock = await connection.execute(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS acquired", (_LOCK,)
    )
    locked = await lock.fetchone()
    if locked is None or not locked["acquired"]:
        return 0
    cursor = await connection.execute(
        "WITH candidates AS ("
        "SELECT body.digest, octet_length(body.body) AS bytes "
        "FROM inventory_snapshot_properties body "
        "WHERE NOT EXISTS (SELECT 1 FROM inventory_snapshot_resource_row resource "
        "WHERE resource.props_digest=body.digest) "
        "AND NOT EXISTS (SELECT 1 FROM inventory_snapshot_link_row link "
        "WHERE link.props_digest=body.digest) "
        "ORDER BY body.digest LIMIT %s), "
        "budget AS (SELECT digest, SUM(bytes) OVER (ORDER BY digest) AS total FROM candidates) "
        "DELETE FROM inventory_snapshot_properties body USING budget "
        "WHERE body.digest=budget.digest AND budget.total<=%s",
        (limit, max_bytes),
    )
    return max(0, cursor.rowcount)
