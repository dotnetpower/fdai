"""Bounded candidate retrieval over prepared immutable ontology snapshots."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.providers.catalog_search import CatalogGenerationMetadata, CatalogSearchDocument

from .ontology_candidate_authorization import (
    AuthorizedOntologyCandidates,
    reauthorize_ontology_candidates,
)
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection
from .ontology_snapshot_validation import OntologySnapshotValidation
from .ontology_vector_store import OntologyVectorSnapshotStore
from .ranking import CatalogRankingPolicy, rank_documents


@dataclass(frozen=True, slots=True)
class OntologyCandidateSearchResult:
    """Candidate accounting, with facts only from the current authorized graph."""

    authorized: AuthorizedOntologyCandidates | None
    matched_candidate_count: int
    returned_candidate_count: int
    truncated: bool
    scores: tuple[tuple[str, float], ...]
    manifest_digest: str
    ontology_release_digest: str
    execution_authority: Literal[False] = False
    authority: Literal["candidate_only"] = "candidate_only"


@dataclass(frozen=True, slots=True)
class _Prepared:
    staged: OntologyStagedProjection
    manifest_digest: str
    principal_scope_digest: str
    generation: CatalogGenerationMetadata
    documents: tuple[CatalogSearchDocument, ...]


_ScopeKey = tuple[str, str, tuple[str, ...]]


def _scope_key(manifest: QueryManifest) -> _ScopeKey:
    return (
        manifest.coverage_receipt.principal_scope_digest,
        manifest.principal_role.value,
        manifest.purposes,
    )


class OntologyInstanceCandidateReader:
    """Prepare off-path; search never reloads a full corpus or trusts stored facts.

    The lifecycle owner must supply the independently validated snapshot. This
    reader has no activation authority. It retains one generation per bounded scope, and
    exact object or document identifiers bypass query embedding. An empty index
    result is only a no-candidate outcome, never proof of graph absence.
    """

    def __init__(
        self,
        *,
        snapshots: OntologyGenerationSnapshotStore,
        vectors: OntologyVectorSnapshotStore,
        ranking_policy: CatalogRankingPolicy,
        max_prepared_scopes: int = 8,
        max_prepared_documents: int = 20_000,
        semantic_search_available: bool = True,
    ) -> None:
        if not 1 <= max_prepared_scopes <= 32 or not 1 <= max_prepared_documents <= 20_000:
            raise ValueError("ontology candidate cache capacity must be bounded")
        self._snapshots, self._vectors, self._policy = snapshots, vectors, ranking_policy
        self._semantic_search_available = semantic_search_available
        self._max_scopes, self._max_documents = max_prepared_scopes, max_prepared_documents
        self._prepared: dict[_ScopeKey, _Prepared] = {}
        self._preparing: dict[_ScopeKey, object] = {}
        self._pending_tokens: set[object] = set()

    async def prepare(
        self,
        *,
        staged: OntologyStagedProjection,
        vector_digest: str,
        manifest: QueryManifest,
        validation: OntologySnapshotValidation,
    ) -> None:
        """Replace the local immutable read cache only after complete successful loading."""
        if (
            validation.validator_id != "Heimdall"
            or validation.snapshot_digest != staged.snapshot_digest
            or validation.source_generation != staged.source_generation
            or validation.source_projection_digest != staged.source_projection_digest
            or validation.manifest_digest != manifest.manifest_digest
            or validation.principal_scope_digest != manifest.coverage_receipt.principal_scope_digest
        ):
            raise ValueError("ontology candidate preparation requires exact independent validation")
        scope = _scope_key(manifest)
        occupied_scopes = self._prepared.keys() | self._preparing.keys()
        if (scope not in occupied_scopes and len(occupied_scopes) >= self._max_scopes) or len(
            self._pending_tokens
        ) >= self._max_scopes:
            raise ValueError("ontology candidate cache scope capacity exceeded")
        token = object()
        self._preparing[scope] = token
        self._pending_tokens.add(token)
        try:
            prepared = await self._load(staged, vector_digest, manifest, validation)
            if self._preparing.get(scope) is not token:
                raise ValueError("ontology candidate preparation was invalidated")
            retained_count = sum(
                len(item.documents) for key, item in self._prepared.items() if key != scope
            )
            if retained_count + len(prepared.documents) > self._max_documents:
                raise ValueError("ontology candidate cache document capacity exceeded")
            self._prepared[scope] = prepared
        finally:
            self._pending_tokens.discard(token)
            if self._preparing.get(scope) is token:
                del self._preparing[scope]

    async def _load(
        self,
        staged: OntologyStagedProjection,
        vector_digest: str,
        manifest: QueryManifest,
        validation: OntologySnapshotValidation,
    ) -> _Prepared:
        async with asyncio.timeout(120):
            build = await self._snapshots.read(
                staged.snapshot_digest,
                manifest=manifest,
                source_generation=staged.source_generation,
                source_projection_digest=staged.source_projection_digest,
            )
            if build is None or build.metadata.generation_digest != validation.generation_digest:
                raise ValueError("ontology candidate source snapshot identity mismatch")
            documents: list[CatalogSearchDocument] = []
            for offset in range(0, len(build.documents), 1000):
                page = build.documents[offset : offset + 1000]
                vectors = await self._vectors.read(
                    vector_digest,
                    snapshot_digest=staged.snapshot_digest,
                    generation=build.metadata,
                    document_ids=tuple(item.rule_id for item in page),
                )
                documents.extend(
                    replace(item, embedding=vectors[item.rule_id])
                    for item in page
                    if item.document_kind == "ontology_object"
                )
            return _Prepared(
                staged,
                manifest.manifest_digest,
                manifest.coverage_receipt.principal_scope_digest,
                build.metadata,
                tuple(documents),
            )

    async def search(
        self,
        query: str,
        *,
        staged: OntologyStagedProjection,
        manifest: QueryManifest,
        gateway: SecuredObjectSetQueryGateway,
        as_of: datetime,
        limit: int = 20,
    ) -> OntologyCandidateSearchResult:
        """Return current authorized facts or hold on any stale candidate binding."""
        if not query.strip() or len(query.encode("utf-8")) > 16_384 or not 1 <= limit <= 100:
            raise ValueError("ontology candidate query and result limit must be bounded")
        scope = _scope_key(manifest)
        prepared = self._prepared.get(scope)
        if (
            prepared is None
            or prepared.staged != staged
            or prepared.manifest_digest != manifest.manifest_digest
            or prepared.principal_scope_digest != manifest.coverage_receipt.principal_scope_digest
        ):
            raise ValueError("ontology candidate generation is not prepared for the current scope")
        async with asyncio.timeout(5):
            exact = tuple(
                document
                for document in prepared.documents
                if query == document.rule_id or query == json.loads(document.text)["id"]
            )
            if exact:
                ranked = tuple((self._policy.exact_weight, item) for item in exact)
            else:
                if not self._semantic_search_available:
                    raise ValueError("ontology instance semantic ranking is not qualified")
                vector = await self._vectors.embed_query(query, generation=prepared.generation)
                ranked = tuple(
                    (score, document)
                    for score, document, _components in rank_documents(
                        prepared.documents,
                        query,
                        policy=self._policy,
                        query_vector=vector,
                    )
                )
            selected = tuple(document for _score, document in ranked[:limit])
            authorized = (
                await reauthorize_ontology_candidates(
                    candidates=selected,
                    staged=staged,
                    manifest=manifest,
                    gateway=gateway,
                    as_of=as_of,
                )
                if selected
                else None
            )
            if self._prepared.get(scope) is not prepared:
                raise ValueError("ontology candidate query was invalidated")
            return OntologyCandidateSearchResult(
                authorized,
                len(ranked),
                len(selected),
                len(ranked) > limit,
                tuple((item.rule_id, score) for score, item in ranked[:limit]),
                manifest.manifest_digest,
                manifest.release_digest,
            )

    def invalidate(self, *, principal_scope_digest: str | None = None) -> None:
        """Withdraw a principal's cache and pending preparation, or all scopes on shutdown."""
        for scope in self._prepared.keys() | self._preparing.keys():
            if principal_scope_digest is None or scope[0] == principal_scope_digest:
                self._prepared.pop(scope, None)
                self._preparing.pop(scope, None)
