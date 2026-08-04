from __future__ import annotations

from collections.abc import Sequence

from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.shared.providers.catalog_search import CatalogSearchDocument


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
