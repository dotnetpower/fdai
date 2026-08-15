"""In-memory behavior retrieval keeps ordering, freshness, and citation safety."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.knowledge.behavior_index import (
    InMemoryBehaviorKnowledgeIndex,
    TrackedSourceFreshnessValidator,
    normalize_tokens,
)
from fdai.shared.providers.behavior_knowledge import (
    EMBEDDING_DIM,
    BehaviorContent,
    BehaviorSource,
    BehaviorSpec,
)

CODE_PATH = "services/core-control-plane/src/fdai/core/trust/router.py"
TEST_PATH = "services/core-control-plane/tests/trust/test_router.py"
DESIGN_PATH = "docs/roadmap/interfaces/behavior-knowledge.md"

TRACKED = {
    CODE_PATH: "blob-code-1",
    TEST_PATH: "blob-test-1",
    DESIGN_PATH: "blob-design-1",
}


def _source(
    path: str,
    *,
    kind: str = "code",
    role: str = "implementation",
    blob_sha: str | None = None,
) -> BehaviorSource:
    return BehaviorSource(
        source_kind=kind,  # type: ignore[arg-type]
        path=path,
        symbol="TrustRouter.route",
        line_start=10,
        line_end=42,
        blob_sha=blob_sha or TRACKED[path],
        authority_role=role,  # type: ignore[arg-type]
    )


def _spec(
    behavior_id: str,
    *,
    subject_id: str,
    aliases: tuple[str, ...],
    status: str = "implemented",
    sources: tuple[BehaviorSource, ...] | None = None,
    text: str = "trust routing decides tier",
    localized: dict[str, BehaviorContent] | None = None,
    embedding: tuple[float, ...] = (),
) -> BehaviorSpec:
    return BehaviorSpec(
        behavior_id=behavior_id,
        subject_kind="core",
        subject_id=subject_id,
        status=status,  # type: ignore[arg-type]
        owner="TrustRouter",
        question_aliases=aliases,
        trigger=(text,),
        preconditions=("evidence is available",),
        steps=("classify the request",),
        outcomes=("a routed tier",),
        exclusions=("no execution authority",),
        safety=("fail closed on ambiguity",),
        sources=sources
        or (_source(CODE_PATH), _source(TEST_PATH, kind="test", role="verification")),
        indexed_commit="commit-1",
        extractor_version="v1",
        source_manifest_hash="manifest-1",
        localized=localized or {},
        embedding=embedding,
    )


def _index(tracked: dict[str, str] | None = None) -> InMemoryBehaviorKnowledgeIndex:
    return InMemoryBehaviorKnowledgeIndex(
        TrackedSourceFreshnessValidator(tracked_blobs=dict(tracked or TRACKED))
    )


async def test_upsert_is_idempotent() -> None:
    index = _index()
    spec = _spec(
        "behavior-trust", subject_id="trust_router", aliases=("how does trust routing work",)
    )

    assert await index.upsert(spec) is True
    assert await index.upsert(spec) is False
    assert await index.upsert(replace(spec, indexed_commit="commit-2")) is True


async def test_exact_alias_outranks_identifier_and_hybrid() -> None:
    index = _index()
    await index.upsert(
        _spec(
            "behavior-alias", subject_id="alias_subject", aliases=("how does trust routing work",)
        )
    )
    await index.upsert(
        _spec("behavior-identifier", subject_id="trust routing", aliases=("unrelated alias",))
    )
    await index.upsert(
        _spec("behavior-hybrid", subject_id="quality_gate", aliases=("quality gate alias",))
    )

    results = await index.search("How does trust routing work?", k=3)

    assert [result.spec.behavior_id for result in results] == [
        "behavior-alias",
        "behavior-identifier",
        "behavior-hybrid",
    ]
    assert [result.match_kind for result in results] == [
        "exact_alias",
        "exact_identifier",
        "hybrid",
    ]


async def test_implemented_test_backed_outranks_designed_only() -> None:
    index = _index()
    await index.upsert(
        _spec(
            "behavior-designed",
            subject_id="trust routing",
            aliases=("designed alias",),
            status="designed",
            sources=(_source(DESIGN_PATH, kind="doc", role="design"),),
        )
    )
    await index.upsert(
        _spec("behavior-implemented", subject_id="trust routing", aliases=("implemented alias",))
    )

    results = await index.search("trust routing", k=2)

    assert [result.spec.behavior_id for result in results] == [
        "behavior-implemented",
        "behavior-designed",
    ]


async def test_stale_blob_is_reported_without_dropping_the_record() -> None:
    index = _index()
    await index.upsert(
        _spec(
            "behavior-stale",
            subject_id="trust routing",
            aliases=("stale alias",),
            sources=(_source(CODE_PATH, blob_sha="blob-code-outdated"),),
        )
    )

    (result,) = await index.search("trust routing", k=1)

    assert result.stale is True
    assert [source.path for source in result.stale_sources] == [CODE_PATH]


async def test_untracked_source_is_never_fresh() -> None:
    index = _index()
    await index.upsert(
        _spec(
            "behavior-untracked",
            subject_id="trust routing",
            aliases=("untracked alias",),
            sources=(
                BehaviorSource(
                    source_kind="code",
                    path="infra/terraform.tfstate",
                    symbol="state",
                    line_start=1,
                    line_end=2,
                    blob_sha="blob-code-1",
                    authority_role="implementation",
                ),
            ),
        )
    )

    (result,) = await index.search("trust routing", k=1)

    assert result.stale is True


async def test_korean_paraphrase_retrieves_the_localized_contract() -> None:
    index = _index()
    await index.upsert(
        _spec(
            "behavior-localized",
            subject_id="trust_router",
            aliases=("trust routing alias",),
            localized={
                "ko": BehaviorContent(
                    trigger=("신뢰 라우팅이 계층을 결정합니다",),
                    preconditions=("근거가 있어야 합니다",),
                    steps=("요청을 분류합니다",),
                    outcomes=("라우팅된 계층",),
                    exclusions=("실행 권한 없음",),
                    safety=("모호하면 닫힘으로 실패합니다",),
                )
            },
        )
    )
    await index.upsert(_spec("behavior-other", subject_id="cost_model", aliases=("cost alias",)))

    results = await index.search("신뢰 라우팅은 어떻게 계층을 결정하나요", k=1)

    assert [result.spec.behavior_id for result in results] == ["behavior-localized"]


async def test_comparison_returns_two_fresh_contracts() -> None:
    index = _index()
    await index.upsert(_spec("behavior-a", subject_id="trust routing", aliases=("a alias",)))
    await index.upsert(_spec("behavior-b", subject_id="quality gate", aliases=("b alias",)))

    compared = await index.compare("compare trust routing and quality gate")

    assert sorted(result.spec.behavior_id for result in compared) == ["behavior-a", "behavior-b"]


async def test_comparison_withholds_a_stale_contract() -> None:
    index = _index()
    await index.upsert(_spec("behavior-a", subject_id="trust routing", aliases=("a alias",)))
    await index.upsert(
        _spec(
            "behavior-b",
            subject_id="quality gate",
            aliases=("b alias",),
            sources=(_source(CODE_PATH, blob_sha="blob-code-outdated"),),
        )
    )

    compared = await index.compare("compare trust routing and quality gate")

    assert [result.spec.behavior_id for result in compared] == ["behavior-a"]


async def test_results_expose_citations_without_source_bodies() -> None:
    index = _index()
    await index.upsert(_spec("behavior-cite", subject_id="trust routing", aliases=("cite alias",)))

    (result,) = await index.search("trust routing", k=1)
    citation = result.spec.sources[0].citation()

    assert set(citation) == {"path", "symbol", "line_start", "line_end", "blob_sha"}
    assert not hasattr(result.spec.sources[0], "body")


async def test_low_confidence_hybrid_stays_below_the_retrieval_floor() -> None:
    index = _index()
    await index.upsert(_spec("behavior-far", subject_id="cost_model", aliases=("cost alias",)))

    assert await index.search("unrelated deployment question", k=1) == ()


async def test_search_k_is_bounded() -> None:
    index = _index()
    await index.upsert(_spec("behavior-a", subject_id="trust routing", aliases=("a alias",)))

    for invalid in (0, 21):
        with pytest.raises(ValueError, match="k MUST be"):
            await index.search("trust routing", k=invalid)
    with pytest.raises(ValueError, match="at least two"):
        await index.compare("trust routing", k=1)


async def test_semantic_candidates_fuse_with_lexical_candidates() -> None:
    class _Embedder:
        async def embed(self, text: str) -> list[float]:
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    index = InMemoryBehaviorKnowledgeIndex(
        TrackedSourceFreshnessValidator(tracked_blobs=dict(TRACKED)),
        embedder=_Embedder(),
    )
    aligned = tuple([1.0] + [0.0] * (EMBEDDING_DIM - 1))
    await index.upsert(
        _spec(
            "behavior-semantic",
            subject_id="tier selection",
            aliases=("semantic alias",),
            text="routing decides the tier",
            embedding=aligned,
        )
    )

    (result,) = await index.search("routing decides the tier", k=1)

    assert result.spec.behavior_id == "behavior-semantic"
    assert result.score > 0


def test_token_normalization_separates_identifiers_and_korean_particles() -> None:
    tokens = normalize_tokens("TrustRouter_routes 정책들을")

    assert "trustrouter" in tokens
    assert "route" in tokens
    assert "정책" in tokens
