from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fdai.delivery.catalog_search import (
    index_shipped_catalog,
    load_shipped_catalog_reference_sources,
    publish_shipped_catalog_generation,
)
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    CatalogSearchResult,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


class _RecordingIndex:
    def __init__(self) -> None:
        self.documents: tuple[CatalogSearchDocument, ...] = ()
        self.staged: CatalogGenerationMetadata | None = None

    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int:
        self.documents = tuple(documents)
        return len(self.documents)

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        return await self.upsert(documents)

    async def search(self, query: str, *, k: int = 20) -> Sequence[CatalogSearchResult]:
        return ()

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int:
        self.staged = metadata
        self.documents = tuple(documents)
        return len(documents)

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        activated_at: datetime,
    ) -> CatalogGenerationMetadata:
        assert self.staged is not None
        assert generation_id == self.staged.generation_id
        assert expected_generation_digest == self.staged.generation_digest
        return replace(self.staged, state="active", activated_at=activated_at)

    async def active_generation(
        self, corpus: CatalogCorpus = "active"
    ) -> CatalogGenerationMetadata | None:
        del corpus
        return self.staged


async def test_shipped_catalog_indexing_is_grounded_and_deterministic() -> None:
    index = _RecordingIndex()

    changed = await index_shipped_catalog(index=index, repo_root=_REPO_ROOT)

    assert changed == len(index.documents)
    assert changed > 0
    assert tuple(document.rule_id for document in index.documents) == tuple(
        sorted(document.rule_id for document in index.documents)
    )
    assert all(document.text and document.neighbor_ids for document in index.documents)
    assert all(not document.embedding for document in index.documents)


def test_shipped_catalog_sources_include_exact_manifest_per_rule() -> None:
    from fdai.delivery.catalog_search import load_shipped_catalog_search_sources

    sources = load_shipped_catalog_search_sources(repo_root=_REPO_ROOT)

    assert set(sources.semantic_manifests) == {rule.id for rule in sources.rules}
    assert all(
        manifest.corpus.value == "active" for manifest in sources.semantic_manifests.values()
    )


def test_reference_loader_does_not_require_opa_semantic_parsing() -> None:
    sources = load_shipped_catalog_reference_sources(repo_root=_REPO_ROOT)

    assert sources.rules
    assert sources.ontology_release_digest.startswith("sha256:")


async def test_validated_generation_publisher_stages_then_activates() -> None:
    index = _RecordingIndex()
    active = await publish_shipped_catalog_generation(
        index=index,
        repo_root=_REPO_ROOT,
        validation_receipt_digest="sha256:" + "f" * 64,
        embedding_space_id="catalog-search-384",
        embedding_model_version="test-embedder:1",
        embedding_dimension=384,
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert active.state == "active"
    assert index.staged is not None
    assert index.documents
    assert all(item.manifest_digest for item in index.documents)
