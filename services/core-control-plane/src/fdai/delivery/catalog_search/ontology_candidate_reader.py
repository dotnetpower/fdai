"""Bounded candidate retrieval over prepared immutable ontology snapshots."""

from __future__ import annotations

import asyncio
import json
import re
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
from .ontology_candidate_selection import (
    OntologyCandidateSelection,
    resolve_candidate_selection,
)
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection
from .ontology_snapshot_validation import OntologySnapshotValidation
from .ontology_vector_store import OntologyVectorSnapshotStore, _check_deadline
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
    score_kind: Literal["hybrid_ranking", "exact_identity", "predicate_membership"] = (
        "hybrid_ranking"
    )
    selection_digest: str | None = None


@dataclass(frozen=True, slots=True)
class _Prepared:
    staged: OntologyStagedProjection
    manifest_digest: str
    principal_scope_digest: str
    generation: CatalogGenerationMetadata
    documents: tuple[CatalogSearchDocument, ...]
    resource_type_query_terms: dict[str, tuple[str, ...]]


_ScopeKey = tuple[str, str, tuple[str, ...]]
_OBJECT_DOCUMENT_ID = re.compile(
    r"(?<![A-Za-z0-9._:-])object:[A-Za-z][A-Za-z0-9_]*:[A-Za-z0-9][A-Za-z0-9._:-]{0,1023}"
    r"(?![A-Za-z0-9._:-])"
)


def _scope_key(manifest: QueryManifest) -> _ScopeKey:
    return (
        manifest.coverage_receipt.principal_scope_digest,
        manifest.principal_role.value,
        manifest.purposes,
    )


def _object_document_id_tokens(query: str) -> frozenset[str]:
    return frozenset(token.rstrip(".,;!?") for token in _OBJECT_DOCUMENT_ID.findall(query))


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
        typed_selection_available: bool = False,
        typed_selection_shadow: bool = False,
    ) -> None:
        if not 1 <= max_prepared_scopes <= 32 or not 1 <= max_prepared_documents <= 20_000:
            raise ValueError("ontology candidate cache capacity must be bounded")
        self._snapshots, self._vectors, self._policy = snapshots, vectors, ranking_policy
        self._semantic_search_available = semantic_search_available
        self._typed_selection_available = typed_selection_available
        self._typed_selection_shadow = typed_selection_shadow
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
        """Replace the cache only after complete loading within the preparation deadline."""
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
        deadline = asyncio.get_running_loop().time() + 120
        try:
            prepared = await self._load(staged, vector_digest, manifest, validation, deadline)
            if self._preparing.get(scope) is not token:
                raise ValueError("ontology candidate preparation was invalidated")
            retained_count = sum(
                len(item.documents) for key, item in self._prepared.items() if key != scope
            )
            if retained_count + len(prepared.documents) > self._max_documents:
                raise ValueError("ontology candidate cache document capacity exceeded")
            _check_deadline(deadline)
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
        deadline: float,
    ) -> _Prepared:
        async with asyncio.timeout(max(0.0, deadline - asyncio.get_running_loop().time())):
            _check_deadline(deadline)
            build = await self._snapshots.read(
                staged.snapshot_digest,
                manifest=manifest,
                source_generation=staged.source_generation,
                source_projection_digest=staged.source_projection_digest,
            )
            _check_deadline(deadline)
            if build is None or build.metadata.generation_digest != validation.generation_digest:
                raise ValueError("ontology candidate source snapshot identity mismatch")
            documents: list[CatalogSearchDocument] = []
            for offset in range(0, len(build.documents), 1000):
                _check_deadline(deadline)
                page = build.documents[offset : offset + 1000]
                vectors = await self._vectors.read(
                    vector_digest,
                    snapshot_digest=staged.snapshot_digest,
                    generation=build.metadata,
                    document_ids=tuple(item.rule_id for item in page),
                )
                _check_deadline(deadline)
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
                {
                    key: tuple(value)
                    for key, value in self._snapshots.resource_type_query_terms.items()
                },
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
        selection: OntologyCandidateSelection | None = None,
    ) -> OntologyCandidateSearchResult:
        """Return current authorized facts or hold on any stale candidate binding."""
        return await self._search(
            query,
            staged=staged,
            manifest=manifest,
            gateway=gateway,
            as_of=as_of,
            limit=limit,
            selection=selection,
            typed_permitted=self._semantic_search_available and self._typed_selection_available,
        )

    async def shadow_select(
        self,
        query: str,
        *,
        staged: OntologyStagedProjection,
        manifest: QueryManifest,
        gateway: SecuredObjectSetQueryGateway,
        as_of: datetime,
        selection: OntologyCandidateSelection,
        limit: int = 20,
    ) -> OntologyCandidateSearchResult:
        """Verify typed membership for shadow evidence only; never enables answer ranking."""
        if not self._typed_selection_shadow:
            raise ValueError("ontology instance typed selection shadow is not enabled")
        return await self._search(
            query,
            staged=staged,
            manifest=manifest,
            gateway=gateway,
            as_of=as_of,
            limit=limit,
            selection=selection,
            typed_permitted=True,
        )

    async def _search(
        self,
        query: str,
        *,
        staged: OntologyStagedProjection,
        manifest: QueryManifest,
        gateway: SecuredObjectSetQueryGateway,
        as_of: datetime,
        limit: int,
        selection: OntologyCandidateSelection | None,
        typed_permitted: bool,
    ) -> OntologyCandidateSearchResult:
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
        deadline = asyncio.get_running_loop().time() + 5
        async with asyncio.timeout(5):
            scope_receipts: tuple[str, ...] = ()
            selection_digest: str | None = None
            score_kind: Literal["hybrid_ranking", "exact_identity", "predicate_membership"]
            exact_tokens = _object_document_id_tokens(query)
            exact = tuple(
                document
                for document in prepared.documents
                if query == document.rule_id
                or query == json.loads(document.text)["id"]
                or document.rule_id in exact_tokens
            )
            if selection is not None:
                if not typed_permitted:
                    raise ValueError("ontology instance typed selection is not qualified")
                resolved = await resolve_candidate_selection(
                    selection=selection,
                    query=query,
                    staged=staged,
                    manifest=manifest,
                    documents=prepared.documents,
                    gateway=gateway,
                    as_of=as_of,
                    deadline=deadline,
                    resource_type_query_terms=prepared.resource_type_query_terms,
                )
                ranked = tuple((1.0, item) for item in resolved.documents)
                scope_receipts = resolved.query_receipt_digests
                selection_digest = resolved.selection_digest
                score_kind = "predicate_membership"
            elif exact or exact_tokens:
                ranked = tuple((self._policy.exact_weight, item) for item in exact)
                score_kind = "exact_identity"
            else:
                if not self._semantic_search_available:
                    raise ValueError("ontology instance semantic ranking is not qualified")
                _check_deadline(deadline)
                vector = await self._vectors.embed_query(query, generation=prepared.generation)
                _check_deadline(deadline)
                ranked = tuple(
                    (score, document)
                    for score, document, _components in rank_documents(
                        prepared.documents,
                        query,
                        policy=self._policy,
                        query_vector=vector,
                    )
                )
                score_kind = "hybrid_ranking"
            _check_deadline(deadline)
            selected = tuple(document for _score, document in ranked[:limit])
            authorized = (
                await reauthorize_ontology_candidates(
                    candidates=selected,
                    staged=staged,
                    manifest=manifest,
                    gateway=gateway,
                    as_of=as_of,
                    resource_type_query_terms=prepared.resource_type_query_terms,
                )
                if selected
                else None
            )
            if scope_receipts:
                authorized = (
                    replace(
                        authorized,
                        query_receipt_digests=tuple(
                            dict.fromkeys((*scope_receipts, *authorized.query_receipt_digests))
                        ),
                    )
                    if authorized is not None
                    else AuthorizedOntologyCandidates(
                        objects=(),
                        query_receipt_digests=scope_receipts,
                        snapshot_digest=staged.snapshot_digest,
                        source_generation=staged.source_generation,
                        principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
                    )
                )
            _check_deadline(deadline)
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
                score_kind=score_kind,
                selection_digest=selection_digest,
            )

    def invalidate(self, *, principal_scope_digest: str | None = None) -> None:
        """Withdraw a principal's cache and pending preparation, or all scopes on shutdown."""
        for scope in self._prepared.keys() | self._preparing.keys():
            if principal_scope_digest is None or scope[0] == principal_scope_digest:
                self._prepared.pop(scope, None)
                self._preparing.pop(scope, None)

    def validate_evaluation_binding(
        self,
        *,
        staged: OntologyStagedProjection,
        manifest: QueryManifest,
        generation_digest: str,
        ranking_policy: CatalogRankingPolicy,
        require_typed_selection: bool = False,
    ) -> None:
        """Check frozen diagnostic inputs without preparing or enabling this reader."""
        prepared = self._prepared.get(_scope_key(manifest))
        if (
            prepared is None
            or prepared.staged != staged
            or prepared.manifest_digest != manifest.manifest_digest
            or prepared.generation.generation_digest != generation_digest
            or self._policy != ranking_policy
            or (
                require_typed_selection
                and (not self._semantic_search_available or not self._typed_selection_available)
            )
        ):
            raise ValueError("ontology evaluation reader binding changed")
