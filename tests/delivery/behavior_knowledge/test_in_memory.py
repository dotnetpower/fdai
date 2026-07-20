"""Behavior knowledge reference-index contract tests."""

from __future__ import annotations

from dataclasses import replace

from fdai.delivery.behavior_knowledge import InMemoryBehaviorKnowledgeIndex
from fdai.shared.providers.behavior_knowledge import (
    EMBEDDING_DIM,
    BehaviorFreshness,
    BehaviorSource,
    BehaviorSpec,
)


class KeywordEmbedder:
    async def embed(self, text: str) -> tuple[float, ...]:
        lowered = text.casefold()
        vector = [0.0] * EMBEDDING_DIM
        vector[0] = float("incident" in lowered)
        vector[1] = float("odin" in lowered or "arbitration" in lowered)
        vector[2] = float("issue" in lowered or "duplicate" in lowered)
        return tuple(vector)


class StaleValidator:
    def __init__(self, stale_path: str | None = None) -> None:
        self._stale_path = stale_path

    async def validate(self, source: BehaviorSource) -> BehaviorFreshness:
        fresh = source.path != self._stale_path
        return BehaviorFreshness(
            fresh=fresh,
            tracked=True,
            current_blob_sha=source.blob_sha if fresh else "changed",
        )


def _source(*, kind: str = "code", path: str = "src/fdai/example.py") -> BehaviorSource:
    return BehaviorSource(
        source_kind=kind,  # type: ignore[arg-type]
        path=path,
        symbol="example",
        line_start=10,
        line_end=20,
        blob_sha="blob-sha",
        authority_role="verification" if kind == "test" else "implementation",
    )


def _spec(
    behavior_id: str,
    *,
    subject_id: str,
    alias: str,
    status: str = "implemented",
    sources: tuple[BehaviorSource, ...] | None = None,
) -> BehaviorSpec:
    return BehaviorSpec(
        behavior_id=behavior_id,
        subject_kind="system_behavior",
        subject_id=subject_id,
        status=status,  # type: ignore[arg-type]
        owner="Saga",
        question_aliases=(alias,),
        trigger=("A relevant event arrives.",),
        preconditions=("Authoritative evidence exists.",),
        steps=("Apply the deterministic behavior.",),
        outcomes=("Return a stable result.",),
        exclusions=("This does not grant execution authority.",),
        safety=("Abstain when evidence is stale.",),
        sources=sources or (_source(), _source(kind="test", path="tests/test_example.py")),
        indexed_commit="commit-sha",
        extractor_version="behavior-seed-v1",
        source_manifest_hash="manifest-sha",
    )


async def test_exact_alias_outranks_semantic_similarity() -> None:
    index = InMemoryBehaviorKnowledgeIndex(embedder=KeywordEmbedder())
    exact = _spec(
        "issue-dedup",
        subject_id="Issue.deduplication",
        alias="Issue 중복은 어떻게 처리해?",
    )
    semantic = _spec(
        "issue-general",
        subject_id="Issue",
        alias="How are duplicate issues grouped?",
    )
    await index.upsert(semantic)
    await index.upsert(exact)

    results = await index.search("Issue 중복은 어떻게 처리해?")

    assert [result.spec.behavior_id for result in results[:2]] == [
        "issue-dedup",
        "issue-general",
    ]
    assert results[0].match_kind == "exact_alias"


async def test_reindexing_identical_spec_is_idempotent() -> None:
    index = InMemoryBehaviorKnowledgeIndex(embedder=KeywordEmbedder())
    spec = _spec(
        "incident-id",
        subject_id="Incident.incident_id",
        alias="Incident ID는 어떻게 생성돼?",
    )

    assert await index.upsert(spec)
    stored = (await index.search("Incident ID는 어떻게 생성돼?"))[0].spec
    assert not await index.upsert(replace(stored))
    assert len(await index.search("Incident ID는 어떻게 생성돼?")) == 1


async def test_stale_source_hash_marks_result_stale() -> None:
    path = "src/fdai/example.py"
    index = InMemoryBehaviorKnowledgeIndex(
        embedder=KeywordEmbedder(),
        source_validator=StaleValidator(path),
    )
    await index.upsert(
        _spec(
            "incident-id",
            subject_id="Incident.incident_id",
            alias="Incident ID는 어떻게 생성돼?",
        )
    )

    result = (await index.search("Incident ID는 어떻게 생성돼?"))[0]

    assert result.stale
    assert [source.path for source in result.stale_sources] == [path]


async def test_implemented_test_backed_outranks_designed_only() -> None:
    index = InMemoryBehaviorKnowledgeIndex(embedder=KeywordEmbedder())
    designed = _spec(
        "odin-portfolio-review",
        subject_id="Odin.portfolio_review",
        alias="When does Odin review a portfolio?",
        status="designed",
        sources=(_source(kind="doc", path="docs/design.md"),),
    )
    implemented = _spec(
        "odin-arbitration",
        subject_id="Odin.arbitration",
        alias="When does Odin arbitrate?",
    )
    await index.upsert(designed)
    await index.upsert(implemented)

    results = await index.search("Explain Odin arbitration behavior")

    assert results[0].spec.behavior_id == "odin-arbitration"
    assert results[0].spec.test_backed


def test_source_citation_contains_metadata_but_no_raw_code() -> None:
    citation = _source().citation()

    assert citation == {
        "path": "src/fdai/example.py",
        "symbol": "example",
        "line_start": 10,
        "line_end": 20,
        "blob_sha": "blob-sha",
    }
    assert "text" not in citation
    assert "body" not in citation
