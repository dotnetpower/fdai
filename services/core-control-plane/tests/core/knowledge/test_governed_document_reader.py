"""Authorized governed document reader tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.core.knowledge.governed_document_reader import (
    AuthorizedGovernedDocumentReader,
    GovernedDocumentAccessScope,
    RoleScopedDocumentScopeResolver,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    RetentionPolicy,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    GovernedDocumentSearchResult,
)
from fdai.shared.providers.knowledge import KnowledgeChunk

NOW = datetime(2026, 9, 6, 5, 0, tzinfo=UTC)
DOCUMENT_ID = UUID(int=1)
VERSION_ID = UUID(int=2)


class _Search:
    def __init__(
        self,
        hits: Sequence[KnowledgeChunk],
        *,
        complete: bool = True,
    ) -> None:
        self.hits = tuple(hits)
        self.complete = complete
        self.calls: list[tuple[str, str, frozenset[str], int]] = []

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> Sequence[KnowledgeChunk]:
        self.calls.append((query, collection_id, allowed_access_refs, k))
        return self.hits[:k]

    async def search_governed(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> GovernedDocumentSearchResult:
        hits = tuple(
            await self.search(
                query,
                collection_id=collection_id,
                allowed_access_refs=allowed_access_refs,
                k=k,
            )
        )
        return GovernedDocumentSearchResult(
            hits=hits,
            index_generation="test-document-index:sha256:" + ("a" * 64),
            complete=self.complete,
            limitation=None if self.complete else "index_completeness_unverified",
        )


class _Metadata:
    def __init__(self, versions: Sequence[DocumentVersion]) -> None:
        self.versions = {(item.document_id, item.version_id): item for item in versions}

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        return self.versions[(document_id, version_id)]


class _Access:
    def __init__(self, *, denied_versions: frozenset[UUID] = frozenset()) -> None:
        self.denied_versions = denied_versions

    async def authorize_read(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        del actor_id, actor_groups
        if version.version_id in self.denied_versions:
            raise DocumentAccessDeniedError("denied")


class _Scopes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CeilingRole, str]] = []

    async def resolve(
        self,
        *,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
    ) -> GovernedDocumentAccessScope:
        assert principal_groups == frozenset({"group:responders"})
        self.calls.append((principal_ref, principal_role, purpose))
        return GovernedDocumentAccessScope(
            collection_id="operations",
            allowed_access_refs=frozenset({"collection:operations"}),
            actor_groups=frozenset({"group:responders"}),
        )


def _version(
    *,
    document_id: UUID = DOCUMENT_ID,
    version_id: UUID = VERSION_ID,
    state: DocumentState = DocumentState.READY,
    active: bool = True,
) -> DocumentVersion:
    return DocumentVersion(
        document_id=document_id,
        version_id=version_id,
        upload_id=UUID(int=version_id.int + 10),
        source_name=f"runbook-{version_id.int}.md",
        source_sha256=f"{version_id.int:064x}",
        size_bytes=128,
        media_type="text/markdown",
        observed_format="markdown",
        state=state,
        access=AccessDescriptor(
            reference="collection:operations",
            collection_id="operations",
            reader_groups=("group:responders",),
        ),
        retention=RetentionPolicy(policy_version="retention-v1"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="principal:author",
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(minutes=1),
        active=active,
        available=True,
    )


def _hit(
    *,
    document_id: UUID = DOCUMENT_ID,
    version_id: UUID = VERSION_ID,
    chunk_id: str = "chunk-1",
    score: float = 0.9,
    locator: str = "section:recovery",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        doc_id=f"governed:{document_id}:{version_id}",
        chunk_id=chunk_id,
        text="Verify the health probe before restarting.",
        source_ref=f"document://{document_id}/versions/{version_id}#{chunk_id}",
        score=score,
        metadata={
            "governed_document": "true",
            "document_id": str(document_id),
            "version_id": str(version_id),
            "collection_id": "operations",
            "access_descriptor_ref": "collection:operations",
            "locator": locator,
            "retention_state": "live",
        },
    )


def _reader(
    hits: Sequence[KnowledgeChunk],
    versions: Sequence[DocumentVersion],
    *,
    denied_versions: frozenset[UUID] = frozenset(),
    search_complete: bool = True,
) -> tuple[AuthorizedGovernedDocumentReader, _Search, _Scopes]:
    search = _Search(hits, complete=search_complete)
    scopes = _Scopes()
    return (
        AuthorizedGovernedDocumentReader(
            search=search,
            metadata=_Metadata(versions),
            access=_Access(denied_versions=denied_versions),
            scopes=scopes,
            clock=lambda: NOW,
            retrieval_mode="hybrid",
        ),
        search,
        scopes,
    )


async def test_reader_scopes_search_before_projecting_exact_revision() -> None:
    reader, search, scopes = _reader((_hit(),), (_version(),))

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=2,
    )

    assert len(result.excerpts) == 1
    assert result.excerpts[0].document_revision.endswith(f":sha256:{2:064x}")
    assert result.excerpts[0].instruction_authority is False
    assert result.complete is True
    assert result.retrieval_mode == "hybrid"
    assert search.calls == [("recovery", "operations", frozenset({"collection:operations"}), 8)]
    assert scopes.calls == [("operator-a", CeilingRole.READER, "operations-review")]


async def test_reader_skips_unauthorized_candidates_without_disclosing_them() -> None:
    denied_version = UUID(int=3)
    allowed_hit = _hit()
    denied_hit = _hit(
        document_id=UUID(int=4),
        version_id=denied_version,
        chunk_id="denied",
        score=0.99,
    )
    reader, _, _ = _reader(
        (denied_hit, allowed_hit),
        (
            _version(document_id=UUID(int=4), version_id=denied_version),
            _version(),
        ),
        denied_versions=frozenset({denied_version}),
    )

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=1,
    )

    assert [item.chunk_id for item in result.excerpts] == ["chunk-1"]


async def test_reader_marks_candidate_cap_as_incomplete() -> None:
    hits = tuple(
        _hit(
            document_id=UUID(int=index),
            version_id=UUID(int=100 + index),
            chunk_id=f"chunk-{index}",
            score=1.0 - index / 100,
        )
        for index in range(1, 21)
    )
    versions = tuple(
        _version(document_id=UUID(int=index), version_id=UUID(int=100 + index))
        for index in range(1, 21)
    )
    reader, _, _ = _reader(hits, versions)

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=8,
    )

    assert len(result.excerpts) == 8
    assert result.complete is False
    assert result.limitation == "candidate_limit_reached"


async def test_reader_marks_requested_result_cap_as_incomplete() -> None:
    hits = tuple(
        _hit(
            document_id=UUID(int=index),
            version_id=UUID(int=100 + index),
            chunk_id=f"chunk-{index}",
        )
        for index in range(1, 16)
    )
    versions = tuple(
        _version(document_id=UUID(int=index), version_id=UUID(int=100 + index))
        for index in range(1, 16)
    )
    reader, _, _ = _reader(hits, versions)

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=8,
    )

    assert len(result.excerpts) == 8
    assert result.complete is False
    assert result.limitation == "result_limit_reached"


async def test_reader_requires_provider_attested_index_completeness() -> None:
    reader, _, _ = _reader((_hit(),), (_version(),), search_complete=False)

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=2,
    )

    assert result.complete is False
    assert result.limitation == "index_completeness_unverified"


async def test_reader_binds_displayed_attribution_into_evidence_identity() -> None:
    first_reader, _, _ = _reader((_hit(locator="section:first"),), (_version(),))
    second_reader, _, _ = _reader((_hit(locator="section:second"),), (_version(),))

    first = await first_reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=1,
    )
    second = await second_reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=1,
    )

    assert first.excerpts[0].evidence_ref != second.excerpts[0].evidence_ref


async def test_reader_rejects_source_reference_from_another_revision() -> None:
    mismatched = _hit()
    mismatched = KnowledgeChunk(
        doc_id=mismatched.doc_id,
        chunk_id=mismatched.chunk_id,
        text=mismatched.text,
        source_ref=f"document://{UUID(int=9)}/versions/{VERSION_ID}#chunk-1",
        score=mismatched.score,
        metadata=mismatched.metadata,
    )
    reader, _, _ = _reader((mismatched,), (_version(),))

    with pytest.raises(RuntimeError, match="source reference"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )


async def test_reader_applies_score_floor_and_per_revision_diversity() -> None:
    hits = (
        _hit(chunk_id="chunk-1", score=0.9),
        _hit(chunk_id="chunk-2", score=0.8),
        _hit(chunk_id="chunk-3", score=0.7),
        _hit(
            document_id=UUID(int=5),
            version_id=UUID(int=6),
            chunk_id="low-score",
            score=0.001,
        ),
    )
    reader, _, _ = _reader(
        hits,
        (
            _version(),
            _version(document_id=UUID(int=5), version_id=UUID(int=6)),
        ),
    )

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=4,
    )

    assert [item.chunk_id for item in result.excerpts] == ["chunk-1", "chunk-2"]
    assert result.complete is False
    assert result.limitation == "revision_diversity_limit_reached"


async def test_reader_rejects_revision_scope_mismatch() -> None:
    mismatched = _hit()
    mismatched.metadata["collection_id"] = "other"
    reader, _, _ = _reader((mismatched,), (_version(),))

    with pytest.raises(RuntimeError, match="escaped its authorized scope"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )


async def test_reader_rejects_unreadable_revision() -> None:
    reader, _, _ = _reader(
        (_hit(),),
        (_version(state=DocumentState.DELETED, active=False),),
    )

    with pytest.raises(RuntimeError, match="revision is not readable"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )


async def test_reader_rejects_invalid_locator() -> None:
    reader, _, _ = _reader((_hit(locator=""),), (_version(),))

    with pytest.raises(RuntimeError, match="locator is invalid"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )


async def test_role_scoped_resolver_never_manufactures_group_membership() -> None:
    resolver = RoleScopedDocumentScopeResolver(
        collection_id="operations",
        allowed_access_refs=frozenset({"collection:operations"}),
    )

    reader_scope = await resolver.resolve(
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset(),
        purpose="operations-review",
    )
    assert reader_scope.actor_groups == frozenset()

    scope = await resolver.resolve(
        principal_ref="operator-a",
        principal_role=CeilingRole.CONTRIBUTOR,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
    )
    assert scope.actor_groups == frozenset({"group:responders"})
