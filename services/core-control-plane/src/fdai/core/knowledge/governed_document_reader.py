"""Authorize, revalidate, and project document-search hits for conversations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from fdai_service_contracts.cloud_knowledge import Applicability, CloudSourceEvidence, Freshness
from fdai_service_contracts.document import (
    DocumentDisposition as CurrentDocumentDisposition,
)
from fdai_service_contracts.document import (
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

from fdai.core.knowledge.cloud_reference import (
    ApplicableDocumentSearch,
    ApplicableExactDocumentSearch,
    CloudReferenceReader,
)
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_MAX_EXCERPTS,
    GovernedDocumentCollection,
    GovernedDocumentExcerpt,
)
from fdai.shared.contracts import (
    DocumentPurpose,
    DocumentState,
)
from fdai.shared.contracts import (
    DocumentVersion as LegacyDocumentVersion,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.document_ingestion import (
    CurrentDocumentMetadataStore,
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentMetadataStore,
    ExactGovernedDocumentSearch,
    GovernedDocumentSearch,
)
from fdai.shared.providers.knowledge import KnowledgeChunk

_LEGACY_READY_STATES = frozenset({DocumentState.READY, DocumentState.READY_WITH_WARNINGS})
_CURRENT_READY_STATES = frozenset(
    {CurrentDocumentState.READY, CurrentDocumentState.READY_WITH_WARNINGS}
)
_MAX_CANDIDATES = 20
_MAX_EXCERPTS_PER_REVISION = 2


@dataclass(frozen=True, slots=True)
class GovernedDocumentAccessScope:
    """Server-resolved collection and access memberships for one principal."""

    collection_id: str
    allowed_access_refs: frozenset[str]
    actor_groups: frozenset[str]

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or len(self.collection_id) > 256:
            raise ValueError("governed document collection id MUST be bounded and non-empty")
        if not self.allowed_access_refs or any(
            not value.strip() or len(value) > 512 for value in self.allowed_access_refs
        ):
            raise ValueError("governed document access refs MUST be bounded and non-empty")
        if any(not value.strip() or len(value) > 512 for value in self.actor_groups):
            raise ValueError("governed document actor groups MUST be bounded and non-empty")

    def digest_for(self, principal_ref: str) -> str:
        """Return a content-free identity for the principal-bound search scope."""

        material = "\0".join(
            (
                hashlib.sha256(principal_ref.encode()).hexdigest(),
                self.collection_id,
                *sorted(self.allowed_access_refs),
                "--groups--",
                *sorted(self.actor_groups),
            )
        )
        return f"sha256:{hashlib.sha256(material.encode()).hexdigest()}"


class GovernedDocumentScopeResolver(Protocol):
    """Resolve document access from authenticated server-owned principal context."""

    async def resolve(
        self,
        *,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
    ) -> GovernedDocumentAccessScope: ...


@dataclass(frozen=True, slots=True)
class RoleScopedDocumentScopeResolver:
    """Bind one deployment collection to exact authenticated group claims."""

    collection_id: str
    allowed_access_refs: frozenset[str]

    async def resolve(
        self,
        *,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
    ) -> GovernedDocumentAccessScope:
        del principal_ref, principal_role
        if purpose != "operations-review":
            raise PermissionError("governed document purpose is unsupported")
        return GovernedDocumentAccessScope(
            collection_id=self.collection_id,
            allowed_access_refs=self.allowed_access_refs,
            actor_groups=principal_groups,
        )


class AuthorizedGovernedDocumentReader:
    """Convert only current, authorized search hits into untrusted excerpts."""

    def __init__(
        self,
        *,
        search: GovernedDocumentSearch,
        metadata: DocumentMetadataStore,
        access: DocumentAccessProvider,
        scopes: GovernedDocumentScopeResolver,
        clock: Callable[[], datetime],
        retrieval_mode: Literal["lexical", "hybrid"],
        minimum_score: float = 0.01,
        cloud_reference: CloudReferenceReader | None = None,
    ) -> None:
        if not math.isfinite(minimum_score) or minimum_score < 0:
            raise ValueError("governed document minimum score MUST be finite and non-negative")
        self._search = search
        self._metadata = metadata
        self._access = access
        self._scopes = scopes
        self._clock = clock
        self._retrieval_mode = retrieval_mode
        self._minimum_score = minimum_score
        self._cloud_reference = cloud_reference

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
        target: Applicability | None = None,
        exact_refs: tuple[str, ...] = (),
        context_source: str | None = None,
        conversation_ref: str | None = None,
        document_context_digest: str | None = None,
    ) -> GovernedDocumentCollection:
        """Search an authorized scope and recheck each immutable revision."""

        if not query.strip() or len(query) > 20_000:
            raise ValueError("governed document query MUST be bounded and non-empty")
        if not principal_ref.strip() or len(principal_ref) > 256:
            raise ValueError("governed document principal MUST be bounded and non-empty")
        if not 1 <= limit <= GOVERNED_DOCUMENT_MAX_EXCERPTS:
            raise ValueError("governed document limit is invalid")
        if bool(exact_refs) != (
            context_source in {"channel_attachment", "web_reference"}
            and conversation_ref is not None
            and document_context_digest is not None
        ):
            raise ValueError("exact governed document scope MUST be complete or absent")
        scope = await self._scopes.resolve(
            principal_ref=principal_ref,
            principal_role=principal_role,
            principal_groups=principal_groups,
            purpose=purpose,
        )
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("governed document reader clock MUST be timezone-aware")
        candidate_limit = min(_MAX_CANDIDATES, max(limit * 4, limit))
        exact_identities: tuple[tuple[UUID, UUID], ...] = ()
        exact_versions: dict[tuple[UUID, UUID], CurrentDocumentVersion] = {}
        if exact_refs:
            exact_identities = _exact_identities(exact_refs)
            if not isinstance(self._search, ExactGovernedDocumentSearch) or not isinstance(
                self._metadata, CurrentDocumentMetadataStore
            ):
                raise RuntimeError("exact governed document capabilities are unavailable")
            if (
                context_source is None
                or conversation_ref is None
                or document_context_digest is None
            ):
                raise RuntimeError("exact governed document context is incomplete")
            for identity in exact_identities:
                exact_version = await self._metadata.get_current_version(*identity)
                _validate_exact_version(
                    exact_version,
                    identity,
                    principal_ref=principal_ref,
                    context_source=context_source,
                    conversation_ref=conversation_ref,
                    observed_at=observed_at,
                )
                try:
                    await self._access.authorize_read(
                        actor_id=principal_ref,
                        actor_groups=scope.actor_groups,
                        version=_legacy_document_version(exact_version),
                    )
                except DocumentAccessDeniedError as exc:
                    raise PermissionError("exact governed document access is denied") from exc
                exact_versions[identity] = exact_version
            if target is not None:
                if not isinstance(self._search, ApplicableExactDocumentSearch):
                    raise RuntimeError("exact cloud applicability search is unavailable")
                search_result = await self._search.search_applicable_governed_exact(
                    query,
                    exact_refs=exact_identities,
                    context_source=context_source,
                    conversation_ref=conversation_ref,
                    target=target,
                    k=candidate_limit,
                )
            else:
                search_result = await self._search.search_governed_exact(
                    query,
                    exact_refs=exact_identities,
                    context_source=context_source,
                    conversation_ref=conversation_ref,
                    k=candidate_limit,
                )
        elif target is not None:
            if not isinstance(self._search, ApplicableDocumentSearch):
                raise RuntimeError("applicability-aware document search is unavailable")
            search_result = await self._search.search_applicable_governed(
                query,
                collection_id=scope.collection_id,
                allowed_access_refs=scope.allowed_access_refs,
                target=target,
                k=candidate_limit,
            )
        else:
            search_result = await self._search.search_governed(
                query,
                collection_id=scope.collection_id,
                allowed_access_refs=scope.allowed_access_refs,
                k=candidate_limit,
            )
        hits = search_result.hits
        excerpts: list[GovernedDocumentExcerpt] = []
        excerpts_by_revision: dict[str, int] = {}
        seen_chunks: set[tuple[UUID, UUID, str]] = set()
        result_limit_reached = False
        revision_limit_reached = False
        for hit in hits:
            identity = _hit_identity(hit)
            if exact_identities and identity not in exact_identities:
                raise RuntimeError("exact governed document search widened its identity set")
            _validate_source_ref(hit, identity)
            chunk_key = (identity[0], identity[1], hit.chunk_id)
            if chunk_key in seen_chunks:
                raise RuntimeError("governed document search returned a duplicate chunk")
            seen_chunks.add(chunk_key)
            if exact_identities:
                if not isinstance(self._metadata, CurrentDocumentMetadataStore):
                    raise RuntimeError("exact document metadata capability disappeared")
                exact_version = await self._metadata.get_current_version(*identity)
                if context_source is None or conversation_ref is None:
                    raise RuntimeError("exact document conversation scope disappeared")
                _validate_exact_version(
                    exact_version,
                    identity,
                    principal_ref=principal_ref,
                    context_source=context_source,
                    conversation_ref=conversation_ref,
                    observed_at=observed_at,
                    metadata=hit.metadata,
                )
                exact_versions[identity] = exact_version
                version: CurrentDocumentVersion | LegacyDocumentVersion = exact_version
                access_version = _legacy_document_version(exact_version)
            else:
                legacy_version = await self._metadata.get_version(*identity)
                _validate_version(
                    legacy_version,
                    hit.metadata,
                    scope,
                    observed_at=observed_at,
                )
                version = legacy_version
                access_version = legacy_version
            try:
                await self._access.authorize_read(
                    actor_id=principal_ref,
                    actor_groups=scope.actor_groups,
                    version=access_version,
                )
            except DocumentAccessDeniedError:
                continue
            cloud_source = None
            cloud_status = None
            if version.cloud_knowledge is not None:
                if self._cloud_reference is None:
                    raise RuntimeError("cloud reference source verification is unavailable")
                serialized = hit.metadata.get("cloud_source")
                if not isinstance(serialized, str):
                    raise RuntimeError("cloud reference source provenance is missing")
                indexed_source = CloudSourceEvidence.model_validate_json(serialized)
                cloud_source, pending = await self._cloud_reference.resolve(
                    version.cloud_knowledge, indexed_source.source_id, observed_at
                )
                if indexed_source.model_dump(exclude={"check"}) != cloud_source.model_dump(
                    exclude={"check"}
                ):
                    raise RuntimeError("cloud reference source identity changed")
                if target is not None and not cloud_source.applicability.matches(target):
                    raise RuntimeError("cloud reference applicability is unverified")
                cloud_status = (
                    "update_pending" if pending else cloud_source.freshness(observed_at).value
                )
                if cloud_status == Freshness.UNKNOWN.value:
                    continue
            if hit.score < self._minimum_score:
                continue
            locator = hit.metadata.get("locator")
            if not isinstance(locator, str) or not locator.strip() or len(locator) > 512:
                raise RuntimeError("governed document search result locator is invalid")
            revision = f"version:{version.version_id}:sha256:{version.source_sha256}"
            revision_count = excerpts_by_revision.get(revision, 0)
            if revision_count >= _MAX_EXCERPTS_PER_REVISION:
                revision_limit_reached = True
                continue
            if len(excerpts) >= limit:
                result_limit_reached = True
                continue
            excerpts_by_revision[revision] = revision_count + 1
            excerpt_identity = {
                "document_id": str(version.document_id),
                "document_revision": revision,
                "chunk_id": hit.chunk_id,
                "content_digest": f"sha256:{hashlib.sha256(hit.text.encode()).hexdigest()}",
                "source_name": version.source_name,
                "source_ref": hit.source_ref,
                "locator": locator,
                **(
                    {
                        "cloud_check_digest": hashlib.sha256(
                            cloud_source.check.model_dump_json().encode()
                        ).hexdigest(),
                        "cloud_status": str(cloud_status),
                    }
                    if cloud_source is not None
                    else {}
                ),
            }
            excerpts.append(
                GovernedDocumentExcerpt(
                    evidence_ref=(
                        "document:sha256:"
                        + hashlib.sha256(
                            repr(sorted(excerpt_identity.items())).encode()
                        ).hexdigest()
                    ),
                    document_revision=revision,
                    source_name=version.source_name,
                    source_ref=hit.source_ref,
                    locator=locator,
                    chunk_id=hit.chunk_id,
                    text=hit.text,
                    content_digest=excerpt_identity["content_digest"],
                    score=hit.score,
                    cloud_source=cloud_source,
                    cloud_status=cloud_status,
                    applicability_verified=target is not None and cloud_source is not None,
                )
            )
        candidate_limit_reached = len(hits) >= candidate_limit
        complete = (
            search_result.complete
            and not candidate_limit_reached
            and not result_limit_reached
            and not revision_limit_reached
        )
        limitation = (
            "candidate_limit_reached"
            if candidate_limit_reached
            else "result_limit_reached"
            if result_limit_reached
            else "revision_diversity_limit_reached"
            if revision_limit_reached
            else search_result.limitation
        )
        return GovernedDocumentCollection(
            excerpts=tuple(
                sorted(
                    excerpts,
                    key=lambda item: (-item.score, item.document_revision, item.chunk_id),
                )
            ),
            observed_at=observed_at,
            complete=complete,
            limitation=limitation,
            index_generation=search_result.index_generation,
            access_scope_digest=(
                _exact_access_scope_digest(
                    principal_ref=principal_ref,
                    actor_groups=scope.actor_groups,
                    context_digest=document_context_digest,
                    versions=tuple(exact_versions.values()),
                )
                if exact_identities and document_context_digest is not None
                else scope.digest_for(principal_ref)
            ),
            retrieval_mode=self._retrieval_mode,
        )


def _hit_identity(hit: KnowledgeChunk) -> tuple[UUID, UUID]:
    metadata = hit.metadata
    if metadata.get("governed_document") != "true":
        raise RuntimeError("governed document search returned an invalid result")
    try:
        identity = UUID(str(metadata["document_id"])), UUID(str(metadata["version_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("governed document search result identity is invalid") from exc
    if hit.doc_id != f"governed:{identity[0]}:{identity[1]}":
        raise RuntimeError("governed document search result doc_id is invalid")
    return identity


def _validate_source_ref(hit: KnowledgeChunk, identity: tuple[UUID, UUID]) -> None:
    expected_prefix = f"document://{identity[0]}/versions/{identity[1]}#"
    if (
        not hit.source_ref.startswith(expected_prefix)
        or len(hit.source_ref) > 512
        or not hit.source_ref.removeprefix(expected_prefix)
    ):
        raise RuntimeError("governed document source reference is invalid")


def _validate_version(
    version: object,
    metadata: Mapping[str, object],
    scope: GovernedDocumentAccessScope,
    *,
    observed_at: datetime,
) -> None:
    from fdai.shared.contracts import DocumentVersion

    if not isinstance(version, DocumentVersion):
        raise RuntimeError("governed document metadata returned an invalid version")
    if str(version.document_id) != str(metadata.get("document_id")) or str(
        version.version_id
    ) != str(metadata.get("version_id")):
        raise RuntimeError("governed document revision identity changed during retrieval")
    if version.state not in _LEGACY_READY_STATES or not version.active or not version.available:
        raise RuntimeError("governed document revision is not readable")
    if metadata.get("retention_state") != "live":
        raise RuntimeError("governed document index entry is not active")
    derived_expires_at = version.retention.derived_expires_at
    if derived_expires_at is not None and derived_expires_at <= observed_at:
        raise RuntimeError("governed document derived evidence has expired")
    if DocumentPurpose.KNOWLEDGE_BASE not in version.purposes:
        raise RuntimeError("governed document revision is not knowledge-base evidence")
    if (
        version.access.collection_id != scope.collection_id
        or metadata.get("collection_id") != scope.collection_id
        or version.access.reference not in scope.allowed_access_refs
        or metadata.get("access_descriptor_ref") != version.access.reference
    ):
        raise RuntimeError("governed document revision escaped its authorized scope")


def _exact_identities(refs: tuple[str, ...]) -> tuple[tuple[UUID, UUID], ...]:
    if not 1 <= len(refs) <= 8 or len(refs) != len(set(refs)):
        raise ValueError("exact governed document refs MUST be one to eight unique citations")
    identities: list[tuple[UUID, UUID]] = []
    for ref in refs:
        parts = ref.split(":")
        if len(parts) != 3 or parts[0] != "doc":
            raise ValueError("exact governed document citation is invalid")
        try:
            identities.append((UUID(parts[1]), UUID(parts[2])))
        except ValueError as exc:
            raise ValueError("exact governed document citation is invalid") from exc
    return tuple(identities)


def _validate_exact_version(
    version: CurrentDocumentVersion,
    identity: tuple[UUID, UUID],
    *,
    principal_ref: str,
    context_source: str | None,
    conversation_ref: str,
    observed_at: datetime,
    metadata: Mapping[str, object] | None = None,
) -> None:
    if not isinstance(version, CurrentDocumentVersion):
        raise RuntimeError("exact document metadata returned an invalid version")
    if (version.document_id, version.version_id) != identity:
        raise RuntimeError("exact document revision identity changed during retrieval")
    if (
        version.state not in _CURRENT_READY_STATES
        or version.index_state is not DocumentIndexState.ACTIVE
        or version.retention_state is not DocumentRetentionState.LIVE
        or not version.active
        or not version.available
    ):
        raise RuntimeError("exact document revision is not query-visible")
    if CurrentDocumentPurpose.KNOWLEDGE_BASE not in version.purposes:
        raise PermissionError("exact document revision has an unsupported purpose")
    channel_scope = (
        context_source == "channel_attachment"
        and version.disposition is CurrentDocumentDisposition.SESSION_EPHEMERAL
        and version.scope_kind is DocumentScopeKind.CONVERSATION
        and version.scope_ref == conversation_ref
        and version.uploader_id == principal_ref
    )
    web_scope = (
        context_source == "web_reference"
        and version.disposition is CurrentDocumentDisposition.GOVERNED_KNOWLEDGE
        and version.scope_kind is DocumentScopeKind.COLLECTION
        and version.scope_ref == version.access.collection_id
    )
    if not channel_scope and not web_scope:
        raise PermissionError("exact document revision escaped its conversation scope")
    derived_expires_at = version.retention.derived_expires_at
    if (context_source == "channel_attachment" and derived_expires_at is None) or (
        derived_expires_at is not None and derived_expires_at <= observed_at
    ):
        raise RuntimeError("exact document derived evidence has expired")
    expected_disposition = (
        "session_ephemeral" if context_source == "channel_attachment" else "governed_knowledge"
    )
    expected_scope_kind = "conversation" if context_source == "channel_attachment" else "collection"
    expected_scope_ref = (
        conversation_ref if context_source == "channel_attachment" else version.access.collection_id
    )
    if metadata is not None and (
        metadata.get("document_id") != str(identity[0])
        or metadata.get("version_id") != str(identity[1])
        or metadata.get("collection_id") != version.access.collection_id
        or metadata.get("access_descriptor_ref") != version.access.reference
        or metadata.get("disposition") != expected_disposition
        or metadata.get("scope_kind") != expected_scope_kind
        or metadata.get("scope_ref") != expected_scope_ref
        or metadata.get("retention_state") != "live"
    ):
        raise RuntimeError("exact document index metadata escaped its authorized scope")


def _legacy_document_version(
    version: CurrentDocumentVersion,
) -> LegacyDocumentVersion:
    fields = set(LegacyDocumentVersion.model_fields)
    return LegacyDocumentVersion.model_validate(version.model_dump(mode="json", include=fields))


def _exact_access_scope_digest(
    *,
    principal_ref: str,
    actor_groups: frozenset[str],
    context_digest: str,
    versions: tuple[CurrentDocumentVersion, ...],
) -> str:
    material = {
        "principal_digest": hashlib.sha256(principal_ref.encode()).hexdigest(),
        "actor_groups": sorted(actor_groups),
        "context_digest": context_digest,
        "versions": [
            {
                "document_id": str(version.document_id),
                "version_id": str(version.version_id),
                "revision": version.revision,
                "source_sha256": version.source_sha256,
                "collection_id": version.access.collection_id,
                "access_descriptor_ref": version.access.reference,
                "reader_groups": sorted(version.access.reader_groups),
            }
            for version in versions
        ],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "AuthorizedGovernedDocumentReader",
    "GovernedDocumentAccessScope",
    "GovernedDocumentScopeResolver",
    "RoleScopedDocumentScopeResolver",
]
