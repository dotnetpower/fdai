"""Concurrency: register() must not double-ingest the same doc (TOCTOU)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from fdai.core.knowledge import (
    CodeRepoProvider,
    CodeRepoRegistry,
    DuplicateRegistrationError,
    KnowledgeRegistry,
    KnowledgeSourceKind,
)
from fdai.shared.providers.knowledge import KnowledgeChunk, KnowledgeDocument

_NOW = datetime(2026, 7, 11, tzinfo=UTC)


class _CountingSource:
    """KnowledgeSource that counts ingest calls (with a yield to force interleave)."""

    def __init__(self) -> None:
        self.ingest_calls = 0

    async def ingest(self, documents: Sequence[KnowledgeDocument]) -> int:
        # Yield control so a second concurrent register() can interleave here
        # if the lock were missing - the lock must prevent that.
        await asyncio.sleep(0)
        self.ingest_calls += 1
        return len(documents)

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:  # noqa: ARG002
        return ()


@pytest.mark.asyncio
async def test_concurrent_same_doc_ingests_exactly_once() -> None:
    source = _CountingSource()
    registry = KnowledgeRegistry(source=source, clock=lambda: _NOW)

    async def _reg() -> object:
        return await registry.register(
            doc_id="dup",
            title="t",
            text="body",
            source_ref="ref",
            kind=KnowledgeSourceKind.UPLOAD,
            registered_by="op@example.com",
        )

    results = await asyncio.gather(_reg(), _reg(), return_exceptions=True)

    ok = [r for r in results if not isinstance(r, Exception)]
    dupes = [r for r in results if isinstance(r, DuplicateRegistrationError)]
    assert len(ok) == 1
    assert len(dupes) == 1
    # The critical assertion: the document was ingested exactly once, not twice.
    assert source.ingest_calls == 1


@pytest.mark.asyncio
async def test_concurrent_same_repo_registers_once() -> None:
    registry = CodeRepoRegistry(clock=lambda: _NOW)

    async def _reg() -> object:
        return await registry.register(
            repo_id="r1",
            provider=CodeRepoProvider.GITHUB,
            repository="acme/api",
            registered_by="op@example.com",
        )

    results = await asyncio.gather(_reg(), _reg(), return_exceptions=True)

    ok = [r for r in results if not isinstance(r, Exception)]
    dupes = [r for r in results if isinstance(r, DuplicateRegistrationError)]
    assert len(ok) == 1
    assert len(dupes) == 1
    assert len(await registry.list_all()) == 1
