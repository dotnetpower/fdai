"""Bounded reuse of generation documents after exact MVCC identity checks."""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import psycopg

from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    build_document_digest_manifest,
    catalog_search_document_digest,
)

CacheKey = tuple[str, str, str]
DocumentCache = OrderedDict[CacheKey, tuple[tuple[CatalogSearchDocument, ...], int]]


def verify_document_identity(
    metadata: CatalogGenerationMetadata, documents: Sequence[CatalogSearchDocument]
) -> None:
    actual = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    if actual != metadata.document_digest_manifest:
        raise ValueError("catalog generation document digest manifest mismatch")


def without_embeddings(
    documents: Sequence[CatalogSearchDocument],
) -> tuple[CatalogSearchDocument, ...]:
    return tuple(replace(item, embedding=()) for item in documents)


async def lock_corpus(
    connection: psycopg.AsyncConnection[Any], corpus: CatalogCorpus, *, shared: bool = False
) -> None:
    function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    await connection.execute(
        f"SELECT {function}(hashtextextended(%s, 0))",  # noqa: S608 - fixed function names
        (f"catalog-search:{corpus}",),
    )


async def validation_cache_key(
    connection: psycopg.AsyncConnection[dict[str, Any]],
    metadata: CatalogGenerationMetadata,
    transaction_identity: str,
) -> CacheKey | None:
    """Check every row version; never reuse rows written by this transaction."""
    cursor = await connection.execute(
        "SELECT ordinal, xmin::text AS row_version, cmin::text AS command_version, "
        "ctid::text AS tuple_version FROM catalog_search_generation_document "
        "WHERE generation_id=%s ORDER BY ordinal",
        (metadata.generation_id,),
    )
    versions = await cursor.fetchall()
    own_version = str(int(transaction_identity) & 0xFFFFFFFF)
    if any(str(item["row_version"]) == own_version for item in versions):
        return None
    revision = hashlib.sha256(
        json.dumps(
            {
                "epoch": int(transaction_identity) >> 32,
                "rows": [
                    (
                        int(item["ordinal"]),
                        str(item["row_version"]),
                        str(item["command_version"]),
                        str(item["tuple_version"]),
                    )
                    for item in versions
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return metadata.generation_id, metadata.generation_digest, revision


def retain_validated_documents(
    cache: DocumentCache,
    key: CacheKey | None,
    documents: tuple[CatalogSearchDocument, ...],
    *,
    max_entries: int,
    max_bytes: int,
) -> None:
    """Retain only already-verified immutable documents within count and byte ceilings."""
    size = sum(
        len(item.text.encode("utf-8")) + len(item.rule_id) + sum(map(len, item.neighbor_ids))
        for item in documents
    )
    if key is None or not max_entries or size > max_bytes:
        return
    cache[key] = (documents, size)
    cache.move_to_end(key)
    while len(cache) > max_entries or sum(entry[1] for entry in cache.values()) > max_bytes:
        cache.popitem(last=False)
