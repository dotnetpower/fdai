"""Focused persistence, incremental sync, and 13-seed parity tests for behavior knowledge."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.core.knowledge.behavior_index import (
    InMemoryBehaviorKnowledgeIndex,
    TrackedSourceFreshnessValidator,
)
from fdai.delivery.behavior_knowledge.behavior_seed_generation import build_seed_behavior_specs
from fdai.delivery.persistence.postgres_behavior_knowledge import (
    InProcessPostgresBehaviorStore,
    PostgresBehaviorKnowledgeConfig,
    PostgresBehaviorKnowledgeIndex,
    deserialize_behavior_spec,
    encode_behavior_vector,
    serialize_behavior_spec,
    sync_behavior_knowledge_seeds,
)
from fdai.shared.providers.behavior_knowledge import EMBEDDING_DIM, BehaviorSpec

_REPO_ROOT = Path(__file__).resolve().parents[5]


class _DeterministicEmbedder:
    async def embed(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * EMBEDDING_DIM
        for token in text.lower().split():
            bucket = int(hashlib.sha256(token.encode()).hexdigest(), 16) % EMBEDDING_DIM
            vec[bucket] += 1.0
        return tuple(vec)


def _commit_sha() -> str:
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(  # noqa: S603
        (git, "rev-parse", "HEAD"),
        cwd=_REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _seed_specs() -> tuple[BehaviorSpec, ...]:
    return build_seed_behavior_specs(_REPO_ROOT, indexed_commit=_commit_sha())


def _tracked_blobs(specs: tuple[BehaviorSpec, ...]) -> dict[str, str]:
    return {source.path: source.blob_sha for spec in specs for source in spec.sources}


def test_config_and_vector_encoding_enforced_fail_closed() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresBehaviorKnowledgeConfig(dsn="")
    with pytest.raises(ValueError, match="identifier"):
        PostgresBehaviorKnowledgeConfig(dsn="postgresql://localhost/fdai", table="bad;drop")
    with pytest.raises(ValueError, match="identifier"):
        PostgresBehaviorKnowledgeConfig(dsn="postgresql://localhost/fdai", table="한글테이블")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresBehaviorKnowledgeConfig(dsn="postgresql://localhost/fdai", statement_timeout_ms=0)

    vec = [0.0] * EMBEDDING_DIM
    vec[0] = 0.5
    vec[-1] = -0.25
    literal = encode_behavior_vector(vec)
    assert literal.startswith("[0.5,")
    assert literal.endswith(",-0.25]")
    with pytest.raises(ValueError, match="embedding dim"):
        encode_behavior_vector((1.0, 2.0))
    with pytest.raises(ValueError, match="finite"):
        encode_behavior_vector([float("nan")] * EMBEDDING_DIM)


def test_spec_json_round_trip_preserves_localized_and_citation_only_fields() -> None:
    spec = _seed_specs()[0]
    serialized = serialize_behavior_spec(spec)
    assert all("body" not in src for src in serialized["sources"])
    restored = deserialize_behavior_spec(serialized)
    assert restored == spec


async def test_incremental_sync_upserts_idempotently_prunes_removed_and_skips_stale() -> None:
    specs = _seed_specs()
    tracked = _tracked_blobs(specs)
    validator = TrackedSourceFreshnessValidator(tracked)
    store = InProcessPostgresBehaviorStore()
    index = PostgresBehaviorKnowledgeIndex(
        config=PostgresBehaviorKnowledgeConfig(dsn="postgresql://localhost/fdai"),
        validator=validator,
        store=store,
    )

    obsolete = replace(specs[0], behavior_id="obsolete.removed-seed")
    await index.upsert(obsolete)

    first_receipt = await sync_behavior_knowledge_seeds(
        index,
        validator,
        specs=specs,
        indexed_commit=specs[0].indexed_commit,
    )
    assert len(first_receipt.upserted_ids) == 13
    assert first_receipt.unchanged_ids == ()
    assert first_receipt.pruned_ids == ("obsolete.removed-seed",)
    assert first_receipt.skipped_stale_ids == ()

    second_receipt = await sync_behavior_knowledge_seeds(
        index,
        validator,
        specs=specs,
        indexed_commit=specs[0].indexed_commit,
    )
    assert second_receipt.upserted_ids == ()
    assert len(second_receipt.unchanged_ids) == 13
    assert second_receipt.pruned_ids == ()
    assert second_receipt.skipped_stale_ids == ()

    stale_tracked = dict(tracked)
    stale_path = specs[0].sources[0].path
    stale_tracked[stale_path] = "0" * 40
    stale_validator = TrackedSourceFreshnessValidator(stale_tracked)
    stale_receipt = await sync_behavior_knowledge_seeds(
        index,
        stale_validator,
        specs=specs,
        indexed_commit=specs[0].indexed_commit,
        prune_removed=False,
    )
    assert specs[0].behavior_id in stale_receipt.skipped_stale_ids


async def test_postgres_and_in_memory_adapters_maintain_exact_parity_across_13_seeds() -> None:
    specs = _seed_specs()
    tracked = _tracked_blobs(specs)
    validator = TrackedSourceFreshnessValidator(tracked)
    embedder = _DeterministicEmbedder()
    in_memory = InMemoryBehaviorKnowledgeIndex(validator, embedder=embedder)
    pg_index = PostgresBehaviorKnowledgeIndex(
        config=PostgresBehaviorKnowledgeConfig(dsn="postgresql://localhost/fdai"),
        validator=validator,
        embedder=embedder,
        store=InProcessPostgresBehaviorStore(),
    )

    for spec in specs:
        embedded_vec = await embedder.embed(spec.search_text())
        enriched = replace(spec, embedding=tuple(embedded_vec))
        assert await in_memory.upsert(enriched) is True
        assert await pg_index.upsert(enriched) is True

    for spec in specs:
        for alias in spec.question_aliases:
            mem_hits = await in_memory.search(alias, k=3)
            pg_hits = await pg_index.search(alias, k=3)
            assert [r.spec.behavior_id for r in pg_hits] == [r.spec.behavior_id for r in mem_hits]
            assert [r.match_kind for r in pg_hits] == [r.match_kind for r in mem_hits]
            assert [r.score for r in pg_hits] == [r.score for r in mem_hits]
            assert pg_hits[0].spec.behavior_id == spec.behavior_id
            assert pg_hits[0].match_kind == "exact_alias"
            assert not pg_hits[0].stale

    probe_queries = (
        "IncidentRegistry incident_id_for",
        "Odin Forseti arbitration",
        "Saga issue fingerprint deduplication",
        "TrustRouter QualityGate T2",
        "Vidar rollback ShadowExecutor",
        "오딘 포르세티 중재",
        "브라기 번역기 경로",
    )
    for query in probe_queries:
        mem_res = await in_memory.search(query, k=5)
        pg_res = await pg_index.search(query, k=5)
        assert [(r.spec.behavior_id, r.match_kind, r.score) for r in pg_res] == [
            (r.spec.behavior_id, r.match_kind, r.score) for r in mem_res
        ]

    mem_cmp = await in_memory.compare("Odin arbitration vs TrustRouter routing", k=2)
    pg_cmp = await pg_index.compare("Odin arbitration vs TrustRouter routing", k=2)
    assert [r.spec.behavior_id for r in pg_cmp] == [r.spec.behavior_id for r in mem_cmp]
    assert len(pg_cmp) == 2


async def test_stale_sources_are_flagged_in_search_and_withheld_from_compare() -> None:
    specs = _seed_specs()[:2]
    tracked = _tracked_blobs(specs)
    stale_path = specs[0].sources[0].path
    tracked[stale_path] = "f" * 40
    validator = TrackedSourceFreshnessValidator(tracked)
    pg_index = PostgresBehaviorKnowledgeIndex(
        config=PostgresBehaviorKnowledgeConfig(dsn="postgresql://localhost/fdai"),
        validator=validator,
        store=InProcessPostgresBehaviorStore(),
    )
    for spec in specs:
        await pg_index.upsert(spec)

    hits = await pg_index.search(specs[0].question_aliases[0], k=1)
    assert len(hits) == 1
    assert hits[0].stale is True
    assert hits[0].stale_sources

    compared = await pg_index.compare(f"{specs[0].subject_id} {specs[1].subject_id}", k=2)
    assert all(not item.stale for item in compared)
    assert all(item.spec.behavior_id != specs[0].behavior_id for item in compared)
