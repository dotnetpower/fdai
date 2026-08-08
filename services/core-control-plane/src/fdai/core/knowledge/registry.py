"""Knowledge + code-access registries - the slide-8 config surface.

:class:`KnowledgeRegistry` wraps a
:class:`~fdai.shared.providers.knowledge.KnowledgeSource`: registering a
document ingests it (chunk + embed via the bound source) and records a
:class:`RegisteredDocument` so the console can list what is connected.
Retrieval delegates straight to the source, so grounding stays a single
seam.

:class:`CodeRepoRegistry` records
:class:`CodeRepoRegistration` descriptors (no secrets inline) that a
:class:`~fdai.shared.providers.change_feed.ChangeFeed` adapter consumes.

Stores are Protocols with in-memory defaults; a fork binds a Postgres store
under ``delivery/persistence`` without touching this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from fdai.core.knowledge.models import (
    CodeRepoProvider,
    CodeRepoRegistration,
    KnowledgeSourceKind,
    RegisteredDocument,
)
from fdai.shared.providers.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)


class DuplicateRegistrationError(ValueError):
    """Raised when a doc_id / repo_id is already registered."""


class RegistrationNotFoundError(KeyError):
    """Raised when a repo_id is not registered."""


@runtime_checkable
class KnowledgeRegistryStore(Protocol):
    """Persist the list of registered knowledge documents."""

    async def add(self, record: RegisteredDocument) -> None: ...

    async def list_all(self) -> Sequence[RegisteredDocument]: ...

    async def exists(self, doc_id: str) -> bool: ...


@runtime_checkable
class CodeRepoStore(Protocol):
    """Persist registered code repositories."""

    async def add(self, record: CodeRepoRegistration) -> None: ...

    async def replace(self, record: CodeRepoRegistration) -> None: ...

    async def get(self, repo_id: str) -> CodeRepoRegistration | None: ...

    async def list_all(self) -> Sequence[CodeRepoRegistration]: ...


class InMemoryKnowledgeRegistryStore:
    """Default in-memory store for registered documents."""

    def __init__(self) -> None:
        self._records: dict[str, RegisteredDocument] = {}

    async def add(self, record: RegisteredDocument) -> None:
        self._records[record.doc_id] = record

    async def list_all(self) -> Sequence[RegisteredDocument]:
        return tuple(self._records.values())

    async def exists(self, doc_id: str) -> bool:
        return doc_id in self._records


class InMemoryCodeRepoStore:
    """Default in-memory store for code repositories."""

    def __init__(self) -> None:
        self._records: dict[str, CodeRepoRegistration] = {}

    async def add(self, record: CodeRepoRegistration) -> None:
        self._records[record.repo_id] = record

    async def replace(self, record: CodeRepoRegistration) -> None:
        self._records[record.repo_id] = record

    async def get(self, repo_id: str) -> CodeRepoRegistration | None:
        return self._records.get(repo_id)

    async def list_all(self) -> Sequence[CodeRepoRegistration]:
        return tuple(self._records.values())


class KnowledgeRegistry:
    """Register + index knowledge documents and list what is connected."""

    __slots__ = ("_clock", "_lock", "_source", "_store")

    def __init__(
        self,
        *,
        source: KnowledgeSource,
        store: KnowledgeRegistryStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._store = store or InMemoryKnowledgeRegistryStore()
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        # Serialize register() so two concurrent calls for the same doc_id
        # cannot both pass the exists() check and double-ingest the document
        # into the knowledge source (which would pollute RAG grounding with
        # duplicate chunks).
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        doc_id: str,
        title: str,
        text: str,
        source_ref: str,
        kind: KnowledgeSourceKind,
        registered_by: str,
    ) -> RegisteredDocument:
        """Ingest one document into the knowledge source and record it."""
        async with self._lock:
            if await self._store.exists(doc_id):
                raise DuplicateRegistrationError(f"doc_id already registered: {doc_id}")
            chunk_count = await self._source.ingest(
                [KnowledgeDocument(doc_id=doc_id, text=text, source_ref=source_ref)]
            )
            record = RegisteredDocument(
                doc_id=doc_id,
                source_ref=source_ref,
                kind=kind,
                title=title,
                chunk_count=chunk_count,
                registered_by=registered_by,
                registered_at=self._clock(),
            )
            await self._store.add(record)
            return record

    async def list_registered(self) -> Sequence[RegisteredDocument]:
        return await self._store.list_all()

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:
        """Delegate retrieval to the bound knowledge source."""
        return await self._source.search(query, k=k)


class CodeRepoRegistry:
    """Register + list + enable/disable code repositories (no secrets)."""

    __slots__ = ("_clock", "_lock", "_store")

    def __init__(
        self,
        *,
        store: CodeRepoStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store or InMemoryCodeRepoStore()
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        # Serialize register()/set_enabled() so concurrent same-repo_id calls
        # cannot bypass the duplicate check or race a read-modify-write toggle.
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        repo_id: str,
        provider: CodeRepoProvider,
        repository: str,
        registered_by: str,
        default_branch: str = "main",
        secret_ref: str | None = None,
    ) -> CodeRepoRegistration:
        async with self._lock:
            if await self._store.get(repo_id) is not None:
                raise DuplicateRegistrationError(f"repo_id already registered: {repo_id}")
            record = CodeRepoRegistration(
                repo_id=repo_id,
                provider=provider,
                repository=repository,
                default_branch=default_branch,
                registered_by=registered_by,
                registered_at=self._clock(),
                secret_ref=secret_ref,
            )
            await self._store.add(record)
            return record

    async def set_enabled(self, repo_id: str, *, enabled: bool) -> CodeRepoRegistration:
        async with self._lock:
            record = await self._store.get(repo_id)
            if record is None:
                raise RegistrationNotFoundError(repo_id)
            updated = replace(record, enabled=enabled)
            await self._store.replace(updated)
            return updated

    async def list_all(self) -> Sequence[CodeRepoRegistration]:
        return await self._store.list_all()

    async def get(self, repo_id: str) -> CodeRepoRegistration | None:
        return await self._store.get(repo_id)


__all__ = [
    "CodeRepoRegistry",
    "CodeRepoStore",
    "DuplicateRegistrationError",
    "InMemoryCodeRepoStore",
    "InMemoryKnowledgeRegistryStore",
    "KnowledgeRegistry",
    "KnowledgeRegistryStore",
    "RegistrationNotFoundError",
]
