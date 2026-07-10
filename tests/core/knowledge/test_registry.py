"""Tests for the knowledge + code-access registration surface."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from fdai.core.knowledge import (
    CodeRepoProvider,
    CodeRepoRegistry,
    DuplicateRegistrationError,
    KnowledgeRegistry,
    KnowledgeSourceKind,
    RegistrationNotFoundError,
)
from fdai.shared.providers.knowledge import (
    EmbeddingKnowledgeSource,
    EmptyKnowledgeSource,
)

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


class _HashEmbedder:
    """Deterministic, network-free embedder for tests."""

    async def embed(self, text: str) -> Sequence[float]:
        # A tiny bag-of-chars vector - enough for cosine ranking in tests.
        vec = [0.0] * 26
        for ch in text.lower():
            idx = ord(ch) - 97
            if 0 <= idx < 26:
                vec[idx] += 1.0
        return vec


def _clock() -> datetime:
    return _NOW


@pytest.mark.asyncio
async def test_register_document_indexes_and_records() -> None:
    source = EmbeddingKnowledgeSource(embedder=_HashEmbedder())
    registry = KnowledgeRegistry(source=source, clock=_clock)

    record = await registry.register(
        doc_id="arch-1",
        title="Workload architecture",
        text="The API backend calls MySQL and Azure OpenAI.",
        source_ref="wiki://arch-1",
        kind=KnowledgeSourceKind.ARCHITECTURE,
        registered_by="op@example.com",
    )

    assert record.chunk_count >= 1
    assert record.registered_at == _NOW
    listed = await registry.list_registered()
    assert [r.doc_id for r in listed] == ["arch-1"]


@pytest.mark.asyncio
async def test_register_then_search_retrieves_grounding() -> None:
    source = EmbeddingKnowledgeSource(embedder=_HashEmbedder())
    registry = KnowledgeRegistry(source=source, clock=_clock)
    await registry.register(
        doc_id="d1",
        title="MySQL runbook",
        text="mysql cpu saturation slow query mitigation",
        source_ref="wiki://d1",
        kind=KnowledgeSourceKind.RUNBOOK,
        registered_by="op@example.com",
    )

    chunks = await registry.search("mysql cpu", k=1)

    assert chunks
    assert chunks[0].source_ref == "wiki://d1"


@pytest.mark.asyncio
async def test_empty_source_records_zero_chunks() -> None:
    registry = KnowledgeRegistry(source=EmptyKnowledgeSource(), clock=_clock)

    record = await registry.register(
        doc_id="d1",
        title="t",
        text="anything",
        source_ref="ref",
        kind=KnowledgeSourceKind.UPLOAD,
        registered_by="op@example.com",
    )

    assert record.chunk_count == 0


@pytest.mark.asyncio
async def test_duplicate_doc_rejected() -> None:
    registry = KnowledgeRegistry(source=EmptyKnowledgeSource(), clock=_clock)
    await registry.register(
        doc_id="d1",
        title="t",
        text="x",
        source_ref="r",
        kind=KnowledgeSourceKind.UPLOAD,
        registered_by="op@example.com",
    )

    with pytest.raises(DuplicateRegistrationError):
        await registry.register(
            doc_id="d1",
            title="t2",
            text="y",
            source_ref="r2",
            kind=KnowledgeSourceKind.UPLOAD,
            registered_by="op@example.com",
        )


@pytest.mark.asyncio
async def test_code_repo_register_and_toggle() -> None:
    registry = CodeRepoRegistry(clock=_clock)

    repo = await registry.register(
        repo_id="repo-1",
        provider=CodeRepoProvider.GITHUB,
        repository="acme/api",
        registered_by="op@example.com",
        secret_ref="kv://github-token",
    )

    assert repo.enabled is True
    assert repo.secret_ref == "kv://github-token"

    disabled = await registry.set_enabled("repo-1", enabled=False)
    assert disabled.enabled is False
    assert (await registry.get("repo-1")).enabled is False


@pytest.mark.asyncio
async def test_code_repo_requires_owner_name_shape() -> None:
    registry = CodeRepoRegistry(clock=_clock)

    with pytest.raises(ValueError, match="owner/name"):
        await registry.register(
            repo_id="repo-1",
            provider=CodeRepoProvider.GITHUB,
            repository="not-owner-name",
            registered_by="op@example.com",
        )


@pytest.mark.asyncio
async def test_toggle_unknown_repo_raises() -> None:
    registry = CodeRepoRegistry(clock=_clock)

    with pytest.raises(RegistrationNotFoundError):
        await registry.set_enabled("nope", enabled=False)


@pytest.mark.asyncio
async def test_duplicate_repo_rejected() -> None:
    registry = CodeRepoRegistry(clock=_clock)
    await registry.register(
        repo_id="r1",
        provider=CodeRepoProvider.AZURE_DEVOPS,
        repository="org/project",
        registered_by="op@example.com",
    )

    with pytest.raises(DuplicateRegistrationError):
        await registry.register(
            repo_id="r1",
            provider=CodeRepoProvider.AZURE_DEVOPS,
            repository="org/project",
            registered_by="op@example.com",
        )
