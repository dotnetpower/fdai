from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
)

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64
_D = "sha256:" + "d" * 64
_E = "sha256:" + "e" * 64


def _compatibility(
    previous_release_digest: str = _A,
    candidate_release_digest: str = _A,
) -> OntologyGenerationCompatibilityReceipt:
    return OntologyGenerationCompatibilityReceipt(
        previous_release_digest=previous_release_digest,
        candidate_release_digest=candidate_release_digest,
        checked_declarations=(),
        added_declarations=(),
    )


class _BilingualEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        lowered = text.casefold()
        if "remote desktop" in lowered or "원격 데스크톱" in lowered:
            return (1.0, 0.0, 0.0)
        if "public blob" in lowered or "공개 blob" in lowered:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)


async def test_hybrid_index_retrieves_bilingual_semantic_intent() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_BilingualEmbedder())
    await index.upsert(
        (
            CatalogSearchDocument(
                "network.nsg.no-inbound-any-rdp",
                "Block remote desktop exposure.",
                ("network.nsg", "remediate.restrict-network-access"),
            ),
            CatalogSearchDocument(
                "object-storage.public-access.deny",
                "Disable public blob access.",
                ("object-storage", "remediate.disable-public-access"),
            ),
        )
    )

    korean = await index.search("원격 데스크톱 노출을 차단하는 규칙")
    exact = await index.search("object-storage.public-access.deny")

    assert korean[0].rule_id == "network.nsg.no-inbound-any-rdp"
    assert korean[0].match == "hybrid"
    assert exact[0].rule_id == "object-storage.public-access.deny"
    assert exact[0].match == "exact_id"


async def test_synchronize_removes_rules_absent_from_current_corpus() -> None:
    index = InMemoryCatalogSemanticIndex()
    stale = CatalogSearchDocument("rule.stale", "stale rule", ("resource.one",))
    current = CatalogSearchDocument("rule.current", "current rule", ("resource.one",))
    assert await index.synchronize((stale, current)) == 2

    assert await index.synchronize((current,)) == 1

    stale_results = await index.search("rule.stale")
    assert all(item.rule_id != "rule.stale" for item in stale_results)
    assert (await index.search("rule.current"))[0].rule_id == "rule.current"


async def test_hybrid_index_breaks_equal_scores_by_rule_id() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_BilingualEmbedder())
    await index.upsert(
        (
            CatalogSearchDocument("rule.z", "same words", ("neighbor",)),
            CatalogSearchDocument("rule.a", "same words", ("neighbor",)),
        )
    )

    results = await index.search("same words")

    assert tuple(result.rule_id for result in results) == ("rule.a", "rule.z")


async def test_hybrid_index_retrieves_typed_neighbor_without_text_match() -> None:
    index = InMemoryCatalogSemanticIndex()
    await index.upsert((CatalogSearchDocument("rule.one", "unrelated text", ("typed.target",)),))

    results = await index.search("typed.target")

    assert tuple(result.rule_id for result in results) == ("rule.one",)


def _generation(
    generation_id: str,
    *,
    corpus: str = "active",
    ontology_release_digest: str = _A,
) -> CatalogGenerationMetadata:
    return CatalogGenerationMetadata(
        generation_id=generation_id,
        generation_digest={"gen-a": _A, "gen-b": _B, "gen-c": _E}[generation_id],
        corpus=corpus,  # type: ignore[arg-type]
        catalog_digest=_C,
        semantic_schema_digest=_D,
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="catalog-search-3",
        embedding_model_version="test-embedder:1",
        embedding_dimension=3,
        validation_receipt_digest=_B,
    )


async def test_staged_generation_is_invisible_until_atomic_activation() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_BilingualEmbedder())
    await index.upsert((CatalogSearchDocument("rule.legacy", "legacy words", ("legacy",)),))
    metadata = _generation("gen-a")
    assert (
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument("rule.new", "remote desktop rule", ("network.nsg",)),),
        )
        == 1
    )

    assert (await index.search("legacy words"))[0].rule_id == "rule.legacy"
    with pytest.raises(CatalogGenerationStaleError):
        await index.search("remote desktop", expected_catalog_digest=_C)

    active = await index.activate_generation(
        "gen-a",
        expected_generation_digest=_A,
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    results = await index.search("remote desktop", expected_catalog_digest=_C)

    assert active.state == "active"
    assert results[0].rule_id == "rule.new"
    assert results[0].generation_id == "gen-a"
    assert results[0].generation_digest == _A


async def test_generation_activation_replaces_complete_corpus() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_BilingualEmbedder())
    for generation_id, rule_id, text in (
        ("gen-a", "rule.a", "remote desktop"),
        ("gen-b", "rule.b", "public blob"),
    ):
        metadata = _generation(generation_id)
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(rule_id, text, ("resource",)),),
        )
        await index.activate_generation(
            generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    assert (await index.search("public blob"))[0].rule_id == "rule.b"
    assert all(item.rule_id != "rule.a" for item in await index.search("remote desktop"))


async def test_generation_rollback_reactivates_retained_prior_generation() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_BilingualEmbedder())
    for generation_id, rule_id, text in (
        ("gen-a", "rule.a", "remote desktop"),
        ("gen-b", "rule.b", "public blob"),
    ):
        metadata = _generation(generation_id)
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(rule_id, text, ("resource",)),),
        )
        await index.activate_generation(
            generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    receipt = await index.rollback_generation(
        "gen-a",
        expected_active_generation_id="gen-b",
        expected_active_generation_digest=_B,
        expected_target_generation_digest=_A,
        expected_validation_receipt_digest=_B,
        ontology_compatibility_receipt=_compatibility(),
        rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert receipt.retired_generation_id == "gen-b"
    assert receipt.reactivated_generation_id == "gen-a"
    assert await index.active_generation() == receipt.reactivated_generation
    assert (await index.search("remote desktop"))[0].rule_id == "rule.a"
    assert all(item.rule_id != "rule.b" for item in await index.search("public blob"))
    assert (
        sum(metadata.state == "active" for metadata, _documents in index._generations.values()) == 1
    )


async def test_generation_rollback_rejects_stale_active_revision() -> None:
    index = InMemoryCatalogSemanticIndex()
    for generation_id in ("gen-a", "gen-b", "gen-c"):
        metadata = _generation(generation_id)
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{generation_id}", generation_id, ("resource",)),),
        )
        await index.activate_generation(
            generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    with pytest.raises(CatalogGenerationStaleError, match="stale"):
        await index.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_B,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )

    assert (await index.active_generation()).generation_id == "gen-c"  # type: ignore[union-attr]


async def test_generation_rollback_rejects_wrong_corpus() -> None:
    index = InMemoryCatalogSemanticIndex()
    active = _generation("gen-a")
    discovery = _generation("gen-b", corpus="discovery")
    for metadata in (active, discovery):
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{metadata.generation_id}", "text", ("resource",)),),
        )
        await index.activate_generation(
            metadata.generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="share one corpus"):
        await index.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_B,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )


async def test_generation_rollback_rejects_incompatible_ontology_release() -> None:
    index = InMemoryCatalogSemanticIndex()
    for metadata in (
        _generation("gen-a"),
        _generation("gen-b", ontology_release_digest=_C),
    ):
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{metadata.generation_id}", "text", ("resource",)),),
        )
        await index.activate_generation(
            metadata.generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="ontology compatibility receipt mismatch"):
        await index.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_B,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )


async def test_generation_rollback_accepts_compatible_n_minus_one_release() -> None:
    index = InMemoryCatalogSemanticIndex()
    for metadata in (
        _generation("gen-a"),
        _generation("gen-b", ontology_release_digest=_C),
    ):
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{metadata.generation_id}", "text", ("resource",)),),
        )
        await index.activate_generation(
            metadata.generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    receipt = await index.rollback_generation(
        "gen-a",
        expected_active_generation_id="gen-b",
        expected_active_generation_digest=_B,
        expected_target_generation_digest=_A,
        expected_validation_receipt_digest=_B,
        ontology_compatibility_receipt=_compatibility(_A, _C),
        rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert receipt.reactivated_generation.ontology_release_digest == _A
    assert receipt.retired_generation.ontology_release_digest == _C


async def test_generation_rollback_rejects_wrong_validation_receipt() -> None:
    index = InMemoryCatalogSemanticIndex()
    for generation_id in ("gen-a", "gen-b"):
        metadata = _generation(generation_id)
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{generation_id}", "text", ("resource",)),),
        )
        await index.activate_generation(
            generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="validation receipt mismatch"):
        await index.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=_B,
            expected_target_generation_digest=_A,
            expected_validation_receipt_digest=_D,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("active_digest", "target_digest", "expected_error"),
    (
        (_D, _A, "active catalog generation digest mismatch"),
        (_B, _D, "target catalog generation digest mismatch"),
    ),
)
async def test_generation_rollback_rejects_digest_mismatch(
    active_digest: str,
    target_digest: str,
    expected_error: str,
) -> None:
    index = InMemoryCatalogSemanticIndex()
    for generation_id in ("gen-a", "gen-b"):
        metadata = _generation(generation_id)
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{generation_id}", "text", ("resource",)),),
        )
        await index.activate_generation(
            generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match=expected_error):
        await index.rollback_generation(
            "gen-a",
            expected_active_generation_id="gen-b",
            expected_active_generation_digest=active_digest,
            expected_target_generation_digest=target_digest,
            expected_validation_receipt_digest=_B,
            ontology_compatibility_receipt=_compatibility(),
            rolled_back_at=datetime(2026, 8, 7, tzinfo=UTC),
        )


async def test_generation_rollback_duplicate_retry_returns_same_receipt() -> None:
    index = InMemoryCatalogSemanticIndex()
    for generation_id in ("gen-a", "gen-b"):
        metadata = _generation(generation_id)
        await index.stage_generation(
            metadata,
            (CatalogSearchDocument(f"rule.{generation_id}", "text", ("resource",)),),
        )
        await index.activate_generation(
            generation_id,
            expected_generation_digest=metadata.generation_digest,
            activated_at=datetime(2026, 8, 6, tzinfo=UTC),
        )
    rollback = {
        "expected_active_generation_id": "gen-b",
        "expected_active_generation_digest": _B,
        "expected_target_generation_digest": _A,
        "expected_validation_receipt_digest": _B,
        "ontology_compatibility_receipt": _compatibility(),
        "rolled_back_at": datetime(2026, 8, 7, tzinfo=UTC),
    }

    first = await index.rollback_generation("gen-a", **rollback)  # type: ignore[arg-type]
    duplicate = await index.rollback_generation("gen-a", **rollback)  # type: ignore[arg-type]

    assert duplicate == first
    assert duplicate.receipt_digest == first.receipt_digest
    assert (
        sum(metadata.state == "active" for metadata, _documents in index._generations.values()) == 1
    )


async def test_generation_corpus_and_catalog_identity_are_enforced() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_BilingualEmbedder())
    metadata = _generation("gen-a", corpus="discovery")
    await index.stage_generation(
        metadata,
        (CatalogSearchDocument("rule.candidate", "public blob candidate", ("resource",)),),
    )
    await index.activate_generation(
        "gen-a",
        expected_generation_digest=_A,
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert await index.search("public blob", corpus="active") == ()
    assert (await index.search("public blob", corpus="discovery"))[0].corpus == "discovery"
    with pytest.raises(CatalogGenerationStaleError):
        await index.search(
            "public blob",
            corpus="discovery",
            expected_catalog_digest=_D,
        )
