"""PostgreSQL/pgvector persistence adapter and incremental seed sync for behavior knowledge.

Implements `BehaviorKnowledgeIndex` against PostgreSQL (`jsonb` + `tsvector` +
`pgvector`) while preserving exact match-class, authority, reciprocal-rank
fusion, and tie-breaking parity with `InMemoryBehaviorKnowledgeIndex`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final, Protocol

import psycopg
from psycopg.rows import dict_row

from fdai.core.knowledge.behavior_index import (
    InMemoryBehaviorKnowledgeIndex,
    TrackedSourceFreshnessValidator,
)
from fdai.delivery.behavior_knowledge.behavior_seed_generation import build_seed_behavior_specs
from fdai.shared.providers.behavior_knowledge import (
    EMBEDDING_DIM,
    BehaviorContent,
    BehaviorKnowledgeIndex,
    BehaviorSearchResult,
    BehaviorSource,
    BehaviorSpec,
    Embedder,
)

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_MAX_RESULTS: Final[int] = 20


def encode_behavior_vector(values: Sequence[float]) -> str:
    """Serialize a 384-dim embedding into pgvector's wire literal format."""

    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"behavior embedding dim MUST be {EMBEDDING_DIM}; got {len(values)}")
    if any(isinstance(v, bool) for v in values):
        raise ValueError("behavior embedding values MUST NOT be booleans")
    floats = tuple(float(v) for v in values)
    if any(not math.isfinite(v) for v in floats):
        raise ValueError("behavior embedding values MUST be finite")
    return "[" + ",".join(f"{v:.9g}" for v in floats) + "]"


def serialize_behavior_spec(spec: BehaviorSpec) -> dict[str, Any]:
    """Serialize a `BehaviorSpec` to a citation-only JSON dictionary."""

    return {
        "behavior_id": spec.behavior_id,
        "subject_kind": spec.subject_kind,
        "subject_id": spec.subject_id,
        "status": spec.status,
        "owner": spec.owner,
        "question_aliases": list(spec.question_aliases),
        "trigger": list(spec.trigger),
        "preconditions": list(spec.preconditions),
        "steps": list(spec.steps),
        "outcomes": list(spec.outcomes),
        "exclusions": list(spec.exclusions),
        "safety": list(spec.safety),
        "sources": [source.manifest_record() for source in spec.sources],
        "indexed_commit": spec.indexed_commit,
        "extractor_version": spec.extractor_version,
        "source_manifest_hash": spec.source_manifest_hash,
        "localized": {
            locale: asdict(content) for locale, content in sorted(spec.localized.items())
        },
        "embedding": list(spec.embedding),
    }


def deserialize_behavior_spec(payload: Mapping[str, Any]) -> BehaviorSpec:
    """Reconstruct a `BehaviorSpec` from its stored JSON payload."""

    localized_raw = payload.get("localized", {})
    localized = {
        str(locale): BehaviorContent(
            trigger=tuple(content["trigger"]),
            preconditions=tuple(content["preconditions"]),
            steps=tuple(content["steps"]),
            outcomes=tuple(content["outcomes"]),
            exclusions=tuple(content["exclusions"]),
            safety=tuple(content["safety"]),
        )
        for locale, content in localized_raw.items()
        if isinstance(content, Mapping)
    }
    return BehaviorSpec(
        behavior_id=str(payload["behavior_id"]),
        subject_kind=str(payload["subject_kind"]),
        subject_id=str(payload["subject_id"]),
        status=payload["status"],
        owner=str(payload["owner"]),
        question_aliases=tuple(payload["question_aliases"]),
        trigger=tuple(payload["trigger"]),
        preconditions=tuple(payload["preconditions"]),
        steps=tuple(payload["steps"]),
        outcomes=tuple(payload["outcomes"]),
        exclusions=tuple(payload["exclusions"]),
        safety=tuple(payload["safety"]),
        sources=tuple(BehaviorSource(**src) for src in payload["sources"]),
        indexed_commit=str(payload["indexed_commit"]),
        extractor_version=str(payload["extractor_version"]),
        source_manifest_hash=str(payload["source_manifest_hash"]),
        localized=localized,
        embedding=tuple(float(v) for v in payload.get("embedding", ())),
    )


@dataclass(frozen=True, slots=True)
class PostgresBehaviorKnowledgeConfig:
    dsn: str
    table: str = "behavior_knowledge_contracts"
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn or not self.dsn.strip():
            raise ValueError("PostgresBehaviorKnowledgeConfig.dsn MUST be non-empty")
        if not self.table.isascii() or _IDENTIFIER_RE.fullmatch(self.table) is None:
            raise ValueError("PostgresBehaviorKnowledgeConfig.table MUST be a safe SQL identifier")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresBehaviorKnowledgeConfig timeouts MUST be >= 1")


class BehaviorSqlStorePort(Protocol):
    async def upsert_row(
        self, *, behavior_id: str, payload_json: str, search_text: str, vector_literal: str | None
    ) -> bool: ...
    async def fetch_all_payloads(self) -> tuple[dict[str, Any], ...]: ...
    async def delete_missing(self, retained_ids: Sequence[str]) -> tuple[str, ...]: ...


class InProcessPostgresBehaviorStore(BehaviorSqlStorePort):
    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, str, str | None]] = {}
        self.executed_operations: list[tuple[str, str]] = []

    async def upsert_row(
        self, *, behavior_id: str, payload_json: str, search_text: str, vector_literal: str | None
    ) -> bool:
        self.executed_operations.append(("UPSERT", behavior_id))
        previous = self._rows.get(behavior_id)
        current = (payload_json, search_text, vector_literal)
        self._rows[behavior_id] = current
        return previous != current

    async def fetch_all_payloads(self) -> tuple[dict[str, Any], ...]:
        self.executed_operations.append(("SELECT", "*"))
        return tuple(json.loads(self._rows[key][0]) for key in sorted(self._rows))

    async def delete_missing(self, retained_ids: Sequence[str]) -> tuple[str, ...]:
        retained = set(retained_ids)
        removed = tuple(sorted(key for key in self._rows if key not in retained))
        for key in removed:
            del self._rows[key]
            self.executed_operations.append(("DELETE", key))
        return removed


class _PsycopgBehaviorStore(BehaviorSqlStorePort):
    """Production `psycopg` async SQL store for PostgreSQL + pgvector."""

    def __init__(self, config: PostgresBehaviorKnowledgeConfig) -> None:
        self._config = config

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
        conn = await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )
        try:
            async with conn:
                async with conn.transaction():
                    await conn.execute(
                        f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
                    )
                    yield conn
        finally:
            await conn.close()

    async def upsert_row(
        self,
        *,
        behavior_id: str,
        payload_json: str,
        search_text: str,
        vector_literal: str | None,
    ) -> bool:
        table = self._config.table
        async with self._connection() as conn:
            existing = await (
                await conn.execute(
                    f"SELECT payload, search_text, embedding::text AS vec FROM {table} "  # noqa: S608
                    "WHERE behavior_id = %s",
                    (behavior_id,),
                )
            ).fetchone()
            if existing is not None:
                prev_json = json.dumps(existing["payload"], sort_keys=True, ensure_ascii=False)
                if (
                    prev_json == payload_json
                    and existing.get("search_text") == search_text
                    and existing.get("vec") == vector_literal
                ):
                    return False
            await conn.execute(
                f"INSERT INTO {table} (behavior_id, payload, search_text, embedding) "  # noqa: S608
                "VALUES (%s, %s::jsonb, %s, %s::vector) "
                "ON CONFLICT (behavior_id) DO UPDATE SET "
                "payload = EXCLUDED.payload, "
                "search_text = EXCLUDED.search_text, "
                "embedding = EXCLUDED.embedding",
                (behavior_id, payload_json, search_text, vector_literal),
            )
            return True

    async def fetch_all_payloads(self) -> tuple[dict[str, Any], ...]:
        table = self._config.table
        async with self._connection() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT payload FROM {table} ORDER BY behavior_id ASC"  # noqa: S608
                )
            ).fetchall()
        return tuple(
            row["payload"] if isinstance(row["payload"], dict) else json.loads(str(row["payload"]))
            for row in rows
        )

    async def delete_missing(self, retained_ids: Sequence[str]) -> tuple[str, ...]:
        table = self._config.table
        async with self._connection() as conn:
            rows = await (
                await conn.execute(
                    f"DELETE FROM {table} WHERE NOT (behavior_id = ANY(%s)) "  # noqa: S608
                    "RETURNING behavior_id",
                    (list(retained_ids),),
                )
            ).fetchall()
        return tuple(sorted(str(row["behavior_id"]) for row in rows))


class PostgresBehaviorKnowledgeIndex(BehaviorKnowledgeIndex):
    """Persistent behavior knowledge index with exact in-memory ranking parity."""

    def __init__(
        self,
        *,
        config: PostgresBehaviorKnowledgeConfig,
        validator: TrackedSourceFreshnessValidator,
        embedder: Embedder | None = None,
        store: BehaviorSqlStorePort | None = None,
    ) -> None:
        self._config = config
        self._validator = validator
        self._embedder = embedder
        self._store: BehaviorSqlStorePort = store or _PsycopgBehaviorStore(config)

    async def upsert(self, spec: BehaviorSpec) -> bool:
        if spec.embedding:
            vector_literal: str | None = encode_behavior_vector(spec.embedding)
        elif self._embedder is not None:
            embedded = tuple(float(v) for v in await self._embedder.embed(spec.search_text()))
            spec = replace(spec, embedding=embedded)
            vector_literal = encode_behavior_vector(embedded)
        else:
            vector_literal = None
        payload_json = json.dumps(serialize_behavior_spec(spec), sort_keys=True, ensure_ascii=False)
        return await self._store.upsert_row(
            behavior_id=spec.behavior_id,
            payload_json=payload_json,
            search_text=spec.search_text(),
            vector_literal=vector_literal,
        )

    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResult]:
        if k < 1 or k > _MAX_RESULTS:
            raise ValueError(f"behavior search k MUST be in [1, {_MAX_RESULTS}]")
        payloads = await self._store.fetch_all_payloads()
        if not payloads:
            return ()
        mirror = InMemoryBehaviorKnowledgeIndex(self._validator, embedder=self._embedder)
        for payload in payloads:
            await mirror.upsert(deserialize_behavior_spec(payload))
        return await mirror.search(query, k=k)

    async def compare(self, query: str, *, k: int = 2) -> Sequence[BehaviorSearchResult]:
        if k < 2 or k > _MAX_RESULTS:
            raise ValueError("behavior comparison MUST request at least two contracts")
        results = await self.search(query, k=_MAX_RESULTS)
        return tuple(r for r in results if not r.stale)[:k]

    async def prune_removed(self, retained_ids: Sequence[str]) -> tuple[str, ...]:
        return await self._store.delete_missing(retained_ids)


@dataclass(frozen=True, slots=True)
class BehaviorSeedSyncReceipt:
    """Summary receipt for incremental synchronization of reference behavior seeds."""

    indexed_commit: str
    upserted_ids: tuple[str, ...]
    unchanged_ids: tuple[str, ...]
    pruned_ids: tuple[str, ...]
    skipped_stale_ids: tuple[str, ...]


async def sync_behavior_knowledge_seeds(
    index: PostgresBehaviorKnowledgeIndex,
    validator: TrackedSourceFreshnessValidator,
    *,
    specs: Sequence[BehaviorSpec] | None = None,
    root: Path | None = None,
    indexed_commit: str = "0" * 40,
    prune_removed: bool = True,
) -> BehaviorSeedSyncReceipt:
    """Verify tracked freshness, upsert current seeds, and prune removed seed IDs."""

    resolved_specs = (
        tuple(specs)
        if specs is not None
        else build_seed_behavior_specs(
            root or Path(__file__).resolve().parents[6], indexed_commit=indexed_commit
        )
    )
    upserted: list[str] = []
    unchanged: list[str] = []
    skipped_stale: list[str] = []
    valid_ids: list[str] = []
    for spec in resolved_specs:
        is_stale = False
        for source in spec.sources:
            freshness = await validator.validate(source)
            if not freshness.fresh or not freshness.tracked:
                is_stale = True
                break
        if is_stale:
            skipped_stale.append(spec.behavior_id)
            continue
        valid_ids.append(spec.behavior_id)
        changed = await index.upsert(spec)
        if changed:
            upserted.append(spec.behavior_id)
        else:
            unchanged.append(spec.behavior_id)
    pruned = await index.prune_removed(valid_ids) if prune_removed else ()
    return BehaviorSeedSyncReceipt(
        indexed_commit=indexed_commit,
        upserted_ids=tuple(upserted),
        unchanged_ids=tuple(unchanged),
        pruned_ids=pruned,
        skipped_stale_ids=tuple(skipped_stale),
    )


__all__ = [
    "BehaviorSeedSyncReceipt",
    "BehaviorSqlStorePort",
    "InProcessPostgresBehaviorStore",
    "PostgresBehaviorKnowledgeConfig",
    "PostgresBehaviorKnowledgeIndex",
    "deserialize_behavior_spec",
    "encode_behavior_vector",
    "serialize_behavior_spec",
    "sync_behavior_knowledge_seeds",
]
