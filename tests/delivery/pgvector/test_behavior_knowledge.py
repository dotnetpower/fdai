"""PostgreSQL behavior index offline contracts and live parity coverage."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import replace

import psycopg
import pytest

from fdai.delivery.behavior_knowledge import InMemoryBehaviorKnowledgeIndex
from fdai.delivery.behavior_knowledge.seeds import (
    SEED_SOURCE_PATHS,
    build_seed_behavior_specs,
)
from fdai.delivery.pgvector.behavior_knowledge import (
    PgvectorBehaviorKnowledgeConfig,
    PgvectorBehaviorKnowledgeIndex,
    _content_hash,
    _localized_from_raw,
    _localized_payload,
)
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider

_DIM = 384


class HashEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * _DIM
        for word in text.casefold().split():
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % _DIM
            vector[bucket] += 1.0
        return vector


class StaticSecrets(SecretProvider):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc


def _specs():
    return build_seed_behavior_specs(
        indexed_commit="commit-sha",
        blob_shas={path: f"blob-{position}" for position, path in enumerate(SEED_SOURCE_PATHS)},
    )


def test_config_rejects_unsafe_table_names() -> None:
    with pytest.raises(ValueError, match="identifier"):
        PgvectorBehaviorKnowledgeConfig(dsn_secret="db", spec_table="bad;drop")
    with pytest.raises(ValueError, match="identifier"):
        PgvectorBehaviorKnowledgeConfig(dsn_secret="db", source_table="1bad")


def test_content_hash_is_stable_and_behavior_sensitive() -> None:
    spec = _specs()[0]

    assert _content_hash(spec) == _content_hash(replace(spec))
    assert _content_hash(spec) != _content_hash(replace(spec, owner="OtherOwner"))


def test_localized_content_round_trips_and_changes_content_hash() -> None:
    spec = _specs()[0]
    payload = _localized_payload(spec)

    assert _localized_from_raw(payload) == spec.localized
    assert _localized_from_raw(json.dumps(payload)) == spec.localized
    assert _content_hash(spec) != _content_hash(replace(spec, localized={}))


async def test_search_zero_k_does_not_connect() -> None:
    adapter = PgvectorBehaviorKnowledgeIndex(
        config=PgvectorBehaviorKnowledgeConfig(dsn_secret="db"),
        embedder=HashEmbedder(),
        secrets=StaticSecrets({"db": "postgresql://placeholder"}),
    )

    assert await adapter.search("Incident ID", k=0) == ()


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.integration
async def test_postgres_and_in_memory_rank_parity() -> None:
    dsn = _requires_live_db()
    suffix = uuid.uuid4().hex[:8]
    spec_table = f"behavior_spec_{suffix}"
    source_table = f"behavior_source_{suffix}"
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await connection.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await connection.execute(
            f"""
            CREATE TABLE {spec_table} (
                behavior_id TEXT PRIMARY KEY,
                subject_kind TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                status TEXT NOT NULL,
                owner TEXT NOT NULL,
                question_aliases TEXT[] NOT NULL,
                trigger TEXT[] NOT NULL,
                preconditions TEXT[] NOT NULL,
                processing_steps TEXT[] NOT NULL,
                outcomes TEXT[] NOT NULL,
                exclusions TEXT[] NOT NULL,
                safety TEXT[] NOT NULL,
                localized_content JSONB NOT NULL,
                search_text TEXT NOT NULL,
                alias_search_text TEXT NOT NULL,
                search_vector TSVECTOR NOT NULL,
                embedding vector(384) NOT NULL,
                indexed_commit TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                source_manifest_hash TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                test_backed BOOLEAN NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await connection.execute(
            f"""
            CREATE TABLE {source_table} (
                behavior_id TEXT NOT NULL REFERENCES {spec_table}(behavior_id) ON DELETE CASCADE,
                source_kind TEXT NOT NULL,
                path TEXT NOT NULL,
                symbol TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                blob_sha TEXT NOT NULL,
                authority_role TEXT NOT NULL,
                PRIMARY KEY (behavior_id, path, symbol, line_start, line_end)
            )
            """
        )
        await connection.commit()

    embedder = HashEmbedder()
    reference = InMemoryBehaviorKnowledgeIndex(embedder=embedder)
    adapter = PgvectorBehaviorKnowledgeIndex(
        config=PgvectorBehaviorKnowledgeConfig(
            dsn_secret="db",
            spec_table=spec_table,
            source_table=source_table,
            ivfflat_probes=100,
        ),
        embedder=embedder,
        secrets=StaticSecrets({"db": dsn}),
    )
    try:
        for spec in _specs():
            assert await reference.upsert(spec)
            assert await adapter.upsert(spec)
            assert not await adapter.upsert(spec)

        for query in (
            "Incident ID는 어떻게 생성돼?",
            "언제 Odin이 개입해?",
            "Issue 중복은 어떻게 처리해?",
            "Explain deterministic duplicate behavior",
        ):
            reference_ids = [result.spec.behavior_id for result in await reference.search(query)]
            adapter_ids = [result.spec.behavior_id for result in await adapter.search(query)]
            assert adapter_ids == reference_ids
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(f"DROP TABLE IF EXISTS {source_table}")
            await connection.execute(f"DROP TABLE IF EXISTS {spec_table}")
            await connection.commit()
