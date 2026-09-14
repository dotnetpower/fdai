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
from fdai_service_contracts.document import (
    AccessDescriptor as CurrentAccessDescriptor,
)
from fdai_service_contracts.document import (
    DocumentDisposition,
    DocumentIndexState,
    DocumentRetentionState,
    DocumentScopeKind,
)
from fdai_service_contracts.document import (
    DocumentPurpose as CurrentDocumentPurpose,
)
from fdai_service_contracts.document import (
    DocumentState as CurrentDocumentState,
)
from fdai_service_contracts.document import (
    DocumentVersion as CurrentDocumentVersion,
)
from fdai_service_contracts.document import (
    RetentionPolicy as CurrentRetentionPolicy,
)

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


class _CurrentMetadata:
    def __init__(self, versions: Sequence[CurrentDocumentVersion]) -> None:
        self.versions = {(item.document_id, item.version_id): item for item in versions}
        self.calls: list[tuple[UUID, UUID]] = []

    async def get_current_version(
        self, document_id: UUID, version_id: UUID
    ) -> CurrentDocumentVersion:
        self.calls.append((document_id, version_id))
        return self.versions[(document_id, version_id)]

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        raise AssertionError("exact retrieval used the legacy metadata projection")


class _ExactSearch(_Search):
    def __init__(self, hits: Sequence[KnowledgeChunk]) -> None:
        super().__init__(hits)
        self.exact_calls: list[
            tuple[
                str,
                tuple[tuple[UUID, UUID], ...],
                str,
                str,
                int,
            ]
        ] = []

    async def search_governed_exact(
        self,
        query: str,
        *,
        exact_refs: tuple[tuple[UUID, UUID], ...],
        context_source: str,
        conversation_ref: str,
        k: int = 5,
    ) -> GovernedDocumentSearchResult:
        self.exact_calls.append(
            (
                query,
                exact_refs,
                context_source,
                conversation_ref,
                k,
            )
        )
        return GovernedDocumentSearchResult(
            hits=self.hits[:k],
            index_generation="test-document-index:sha256:" + "b" * 64,
            complete=True,
            limitation=None,
        )


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


def _current_version(
    *,
    document_id: UUID = DOCUMENT_ID,
    version_id: UUID = VERSION_ID,
    conversation_ref: str = "conversation-example",
    collection_id: str = "operations",
    access_descriptor_ref: str = "collection:operations",
    web_reference: bool = False,
) -> CurrentDocumentVersion:
    return CurrentDocumentVersion(
        document_id=document_id,
        version_id=version_id,
        upload_id=UUID(int=version_id.int + 10),
        source_name=f"attachment-{version_id.int}.txt",
        source_sha256=f"{version_id.int:064x}",
        size_bytes=128,
        media_type="text/plain",
        observed_format="text",
        state=CurrentDocumentState.READY,
        access=CurrentAccessDescriptor(
            reference=access_descriptor_ref,
            collection_id=collection_id,
            reader_groups=("group:responders",),
        ),
        retention=CurrentRetentionPolicy(
            policy_version="session-v1",
            source_expires_at=NOW + timedelta(hours=1),
            derived_expires_at=NOW + timedelta(hours=1),
        ),
        purposes=(CurrentDocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="operator-a",
        created_at=NOW - timedelta(minutes=10),
        updated_at=NOW - timedelta(minutes=1),
        active=True,
        available=True,
        disposition=(
            DocumentDisposition.GOVERNED_KNOWLEDGE
            if web_reference
            else DocumentDisposition.SESSION_EPHEMERAL
        ),
        index_state=DocumentIndexState.ACTIVE,
        retention_state=DocumentRetentionState.LIVE,
        scope_kind=(
            DocumentScopeKind.COLLECTION if web_reference else DocumentScopeKind.CONVERSATION
        ),
        scope_ref=collection_id if web_reference else conversation_ref,
    )


def _exact_hit(
    *,
    document_id: UUID = DOCUMENT_ID,
    version_id: UUID = VERSION_ID,
    conversation_ref: str = "conversation-example",
    collection_id: str = "operations",
    access_descriptor_ref: str = "collection:operations",
    web_reference: bool = False,
) -> KnowledgeChunk:
    hit = _hit(document_id=document_id, version_id=version_id)
    return KnowledgeChunk(
        doc_id=hit.doc_id,
        chunk_id=hit.chunk_id,
        text=hit.text,
        source_ref=hit.source_ref,
        score=hit.score,
        metadata={
            **hit.metadata,
            "collection_id": collection_id,
            "access_descriptor_ref": access_descriptor_ref,
            "disposition": "governed_knowledge" if web_reference else "session_ephemeral",
            "scope_kind": "collection" if web_reference else "conversation",
            "scope_ref": collection_id if web_reference else conversation_ref,
        },
    )


def _exact_reader(
    hits: Sequence[KnowledgeChunk],
    versions: Sequence[CurrentDocumentVersion],
) -> tuple[AuthorizedGovernedDocumentReader, _ExactSearch, _CurrentMetadata]:
    search = _ExactSearch(hits)
    metadata = _CurrentMetadata(versions)
    return (
        AuthorizedGovernedDocumentReader(
            search=search,
            metadata=metadata,  # type: ignore[arg-type]
            access=_Access(),
            scopes=_Scopes(),
            clock=lambda: NOW,
            retrieval_mode="hybrid",
        ),
        search,
        metadata,
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


async def test_exact_reader_preauthorizes_all_refs_and_never_calls_broad_search() -> None:
    reader, search, metadata = _exact_reader(
        (
            _exact_hit(
                collection_id="channel-evidence",
                access_descriptor_ref="collection:channel-evidence",
            ),
        ),
        (
            _current_version(
                collection_id="channel-evidence",
                access_descriptor_ref="collection:channel-evidence",
            ),
        ),
    )
    citation = f"doc:{DOCUMENT_ID}:{VERSION_ID}"

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=2,
        exact_refs=(citation,),
        context_source="channel_attachment",
        conversation_ref="conversation-example",
        document_context_digest="sha256:" + "c" * 64,
    )

    assert len(result.excerpts) == 1
    assert metadata.calls == [(DOCUMENT_ID, VERSION_ID), (DOCUMENT_ID, VERSION_ID)]
    assert search.calls == []
    assert search.exact_calls[0][1] == ((DOCUMENT_ID, VERSION_ID),)
    assert search.exact_calls[0][2] == "channel_attachment"
    assert result.access_scope_digest != GovernedDocumentAccessScope(
        collection_id="operations",
        allowed_access_refs=frozenset({"collection:operations"}),
        actor_groups=frozenset({"group:responders"}),
    ).digest_for("operator-a")


async def test_exact_web_reader_accepts_authorized_refs_across_collections() -> None:
    other_document = UUID(int=20)
    other_version = UUID(int=21)
    hits = (
        _exact_hit(web_reference=True),
        _exact_hit(
            document_id=other_document,
            version_id=other_version,
            collection_id="security",
            access_descriptor_ref="collection:security",
            web_reference=True,
        ),
    )
    versions = (
        _current_version(web_reference=True),
        _current_version(
            document_id=other_document,
            version_id=other_version,
            collection_id="security",
            access_descriptor_ref="collection:security",
            web_reference=True,
        ),
    )
    reader, search, _metadata = _exact_reader(hits, versions)
    citations = tuple(f"doc:{version.document_id}:{version.version_id}" for version in versions)

    result = await reader.search(
        query="recovery",
        principal_ref="operator-a",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"group:responders"}),
        purpose="operations-review",
        limit=4,
        exact_refs=citations,
        context_source="web_reference",
        conversation_ref="web-session-example",
        document_context_digest="sha256:" + "c" * 64,
    )

    assert len(result.excerpts) == 2
    assert result.complete is True
    assert search.calls == []
    assert search.exact_calls[0][1] == (
        (DOCUMENT_ID, VERSION_ID),
        (other_document, other_version),
    )


async def test_exact_reader_rejects_conversation_mismatch_before_search() -> None:
    reader, search, _metadata = _exact_reader(
        (_exact_hit(),),
        (_current_version(conversation_ref="another-conversation"),),
    )

    with pytest.raises(PermissionError, match="conversation scope"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=2,
            exact_refs=(f"doc:{DOCUMENT_ID}:{VERSION_ID}",),
            context_source="channel_attachment",
            conversation_ref="conversation-example",
            document_context_digest="sha256:" + "c" * 64,
        )

    assert search.calls == []
    assert search.exact_calls == []


async def test_exact_reader_rejects_provider_identity_widening() -> None:
    other_document = UUID(int=20)
    other_version = UUID(int=21)
    reader, _search, _metadata = _exact_reader(
        (_exact_hit(document_id=other_document, version_id=other_version),),
        (_current_version(),),
    )

    with pytest.raises(RuntimeError, match="widened"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=2,
            exact_refs=(f"doc:{DOCUMENT_ID}:{VERSION_ID}",),
            context_source="channel_attachment",
            conversation_ref="conversation-example",
            document_context_digest="sha256:" + "c" * 64,
        )


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


@pytest.mark.parametrize(
    "values",
    (
        {
            "collection_id": "",
            "allowed_access_refs": frozenset({"access"}),
            "actor_groups": frozenset(),
        },
        {
            "collection_id": "operations",
            "allowed_access_refs": frozenset(),
            "actor_groups": frozenset(),
        },
        {
            "collection_id": "operations",
            "allowed_access_refs": frozenset({"access"}),
            "actor_groups": frozenset({" "}),
        },
    ),
)
def test_access_scope_rejects_unbounded_or_empty_values(values: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="bounded|access refs|actor groups"):
        GovernedDocumentAccessScope(**values)  # type: ignore[arg-type]


async def test_role_scoped_resolver_rejects_unsupported_purpose() -> None:
    resolver = RoleScopedDocumentScopeResolver(
        collection_id="operations",
        allowed_access_refs=frozenset({"collection:operations"}),
    )

    with pytest.raises(PermissionError, match="purpose"):
        await resolver.resolve(
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset(),
            purpose="incident-investigation",
        )


@pytest.mark.parametrize("score", (-1.0, float("nan")))
def test_reader_rejects_invalid_score_floor(score: float) -> None:
    with pytest.raises(ValueError, match="minimum score"):
        AuthorizedGovernedDocumentReader(
            search=_Search(()),
            metadata=_Metadata(()),
            access=_Access(),
            scopes=_Scopes(),
            clock=lambda: NOW,
            retrieval_mode="hybrid",
            minimum_score=score,
        )


@pytest.mark.parametrize(
    ("query", "principal_ref", "limit"),
    (
        ("", "operator-a", 1),
        ("recovery", "", 1),
        ("recovery", "operator-a", 0),
        ("recovery", "operator-a", 9),
    ),
)
async def test_reader_rejects_invalid_request_bounds(
    query: str,
    principal_ref: str,
    limit: int,
) -> None:
    reader, _, _ = _reader((), ())

    with pytest.raises(ValueError, match="query|principal|limit"):
        await reader.search(
            query=query,
            principal_ref=principal_ref,
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=limit,
        )


async def test_reader_rejects_naive_observation_clock() -> None:
    reader = AuthorizedGovernedDocumentReader(
        search=_Search(()),
        metadata=_Metadata(()),
        access=_Access(),
        scopes=_Scopes(),
        clock=lambda: NOW.replace(tzinfo=None),
        retrieval_mode="hybrid",
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )


async def test_reader_rejects_duplicate_chunk_identity() -> None:
    hit = _hit()
    reader, _, _ = _reader((hit, hit), (_version(),))

    with pytest.raises(RuntimeError, match="duplicate chunk"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=2,
        )


@pytest.mark.parametrize("defect", ("marker", "identity", "doc_id"))
async def test_reader_rejects_invalid_hit_identity(defect: str) -> None:
    hit = _hit()
    if defect == "marker":
        hit.metadata["governed_document"] = "false"
    elif defect == "identity":
        hit.metadata.pop("version_id")
    else:
        hit = KnowledgeChunk(
            doc_id="governed:wrong",
            chunk_id=hit.chunk_id,
            text=hit.text,
            source_ref=hit.source_ref,
            score=hit.score,
            metadata=hit.metadata,
        )
    reader, _, _ = _reader((hit,), (_version(),))

    with pytest.raises(RuntimeError, match="invalid result|identity|doc_id"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )


@pytest.mark.parametrize("defect", ("retention", "expiry", "purpose"))
async def test_reader_rejects_ineligible_revision_metadata(defect: str) -> None:
    hit = _hit()
    version = _version()
    if defect == "retention":
        hit.metadata["retention_state"] = "building"
    elif defect == "expiry":
        version = version.model_copy(
            update={
                "retention": RetentionPolicy(
                    policy_version="retention-v1",
                    derived_expires_at=NOW,
                )
            }
        )
    else:
        version = version.model_copy(update={"purposes": ()})
    reader, _, _ = _reader((hit,), (version,))

    with pytest.raises(RuntimeError, match="active|expired|knowledge-base"):
        await reader.search(
            query="recovery",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=1,
        )
