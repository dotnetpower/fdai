from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fdai.delivery.catalog_search import index_shipped_catalog
from fdai.shared.providers.catalog_search import CatalogSearchDocument, CatalogSearchResult

_REPO_ROOT = Path(__file__).resolve().parents[3]


class _RecordingIndex:
    def __init__(self) -> None:
        self.documents: tuple[CatalogSearchDocument, ...] = ()

    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int:
        self.documents = tuple(documents)
        return len(self.documents)

    async def search(self, query: str, *, k: int = 20) -> Sequence[CatalogSearchResult]:
        return ()


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
