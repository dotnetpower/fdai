"""Principal-scoped governed document evidence for RCA grounding."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Protocol
from uuid import UUID

from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    EvidenceLane,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadResult,
)
from fdai.core.operational_context.evidence_bundle_models import canonical_json
from fdai.core.rca.contract import Citation, CitationKind


@dataclass(frozen=True, slots=True)
class GovernedDocumentRevision:
    """Exact immutable document revision eligible for one evidence read."""

    document_id: UUID
    version_id: UUID
    source_sha256: str

    def __post_init__(self) -> None:
        if len(self.source_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_sha256
        ):
            raise ValueError("governed document source_sha256 MUST be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class GovernedDocumentAccessContext:
    """Server-resolved collection and access context for document search."""

    collection_id: str
    access_context_ref: str
    allowed_access_refs: frozenset[str]
    actor_groups: frozenset[str]

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or not self.access_context_ref.strip():
            raise ValueError("governed document collection and access context MUST be non-empty")
        if not self.allowed_access_refs or any(
            not value.strip() for value in self.allowed_access_refs
        ):
            raise ValueError("governed document allowed access refs MUST be non-empty")


@dataclass(frozen=True, slots=True)
class GovernedKnowledgeEvidenceContext:
    """Complete principal, purpose, scope, cutoff, and document access binding."""

    read_request: OperationalEvidenceReadRequest
    authenticated_context: AuthenticatedPrincipalContext
    access_context: GovernedDocumentAccessContext
    expected_revisions: tuple[GovernedDocumentRevision, ...] = ()

    def __post_init__(self) -> None:
        if self.read_request.purpose != self.authenticated_context.purpose:
            raise ValueError("governed knowledge purpose does not match authenticated context")
        revisions = tuple(self.expected_revisions)
        if len({revision.document_id for revision in revisions}) != len(revisions):
            raise ValueError("governed document revision pins MUST have unique document ids")
        object.__setattr__(self, "expected_revisions", revisions)


@dataclass(frozen=True, slots=True)
class GovernedKnowledgeEvidenceResult:
    """Opaque RCA citations or explicit hold reasons, never both."""

    citations: tuple[Citation, ...] = ()
    hold_reasons: tuple[str, ...] = ()
    bundle_id: str | None = None

    def __post_init__(self) -> None:
        if self.citations and self.hold_reasons:
            raise ValueError("governed knowledge evidence cannot cite while held")
        if any(citation.kind is not CitationKind.KNOWLEDGE for citation in self.citations):
            raise ValueError("governed knowledge evidence emits only KNOWLEDGE citations")

    @property
    def hold_required(self) -> bool:
        """Return whether RCA must abstain rather than use this evidence."""

        return bool(self.hold_reasons)


class GovernedKnowledgeEvidenceHoldError(RuntimeError):
    """Typed fail-closed outcome from a governed document reader."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GovernedDocumentEvidenceReader(Protocol):
    """Read governed documents into an operational evidence bundle."""

    async def read(
        self,
        *,
        query: str,
        context: GovernedKnowledgeEvidenceContext,
        limit: int,
    ) -> OperationalEvidenceReadResult: ...


class GovernedKnowledgeEvidenceGatherer:
    """Return opaque governed KNOWLEDGE citations or a fail-closed hold."""

    def __init__(
        self,
        *,
        reader: GovernedDocumentEvidenceReader,
        top_k: int = 5,
    ) -> None:
        if not 1 <= top_k <= 20:
            raise ValueError("governed knowledge top_k MUST be in [1, 20]")
        self._reader = reader
        self._top_k = top_k

    async def gather(
        self,
        *,
        query: str,
        context: GovernedKnowledgeEvidenceContext,
        limit: int | None = None,
    ) -> GovernedKnowledgeEvidenceResult:
        """Gather exact authorized revisions without any unscoped fallback."""

        selected_limit = self._top_k if limit is None else min(max(limit, 1), self._top_k)
        try:
            result = await self._reader.read(
                query=query,
                context=context,
                limit=selected_limit,
            )
        except GovernedKnowledgeEvidenceHoldError as exc:
            return _held(exc.reason)
        except Exception:  # noqa: BLE001 - provider failure cannot disclose or ground evidence
            return _held("provider_unavailable")
        return _citations_from_read(result=result, context=context)


def _citations_from_read(
    *,
    result: OperationalEvidenceReadResult,
    context: GovernedKnowledgeEvidenceContext,
) -> GovernedKnowledgeEvidenceResult:
    bundle = result.bundle
    request = context.read_request
    if (
        result.principal_ref != context.authenticated_context.principal_ref
        or result.execution_authority
        or result.mutation_authority
    ):
        return _held("principal_or_authority_mismatch", bundle.bundle_id)
    if (
        bundle.purpose != request.purpose
        or bundle.scope != tuple(sorted(set(request.scope)))
        or bundle.cutoff != request.cutoff
        or bundle.ontology_release_digest != request.ontology_release_digest
        or bundle.catalog_revision != request.catalog_revision
    ):
        return _held("bundle_identity_mismatch", bundle.bundle_id)
    if bundle.claims or bundle.ontology or bundle.state or bundle.catalog:
        return _held("unexpected_evidence_lane", bundle.bundle_id)
    if bundle.hold_required:
        return GovernedKnowledgeEvidenceResult(
            hold_reasons=tuple(f"bundle_{reason}" for reason in bundle.hold_reasons),
            bundle_id=bundle.bundle_id,
        )
    if not bundle.documents:
        return _held("document_evidence_missing", bundle.bundle_id)

    manifest_entries = tuple(
        entry for entry in bundle.citation_manifest if entry.lane is EvidenceLane.DOCUMENT
    )
    document_refs = tuple(document.evidence_ref for document in bundle.documents)
    manifest_refs = tuple(entry.evidence_ref for entry in manifest_entries)
    if (
        len(manifest_entries) != len(bundle.documents)
        or len(set(manifest_refs)) != len(manifest_refs)
        or set(manifest_refs) != set(document_refs)
    ):
        return _held("citation_manifest_mismatch", bundle.bundle_id)
    manifest = {entry.evidence_ref: entry for entry in manifest_entries}
    citations: list[Citation] = []
    seen: set[str] = set()
    expected_access = governed_access_binding(context)
    for document in bundle.documents:
        entry = manifest.get(document.evidence_ref)
        if entry is None:
            return _held("citation_manifest_missing", bundle.bundle_id)
        source = document.source
        if (
            source.document_revision is None
            or source.source_revision != source.document_revision
            or entry.source_revision != source.document_revision
        ):
            return _held("document_revision_mismatch", bundle.bundle_id)
        if entry.redaction_summary != ("none",):
            return _held("document_redacted", bundle.bundle_id)
        membership = source.membership_evidence_mapping()
        if any(
            canonical_json(membership.get(key)) != canonical_json(value)
            for key, value in expected_access.items()
        ):
            return _held("access_binding_mismatch", bundle.bundle_id)
        if membership.get("document_revision") != source.document_revision:
            return _held("document_revision_mismatch", bundle.bundle_id)
        ref = _opaque_knowledge_ref(
            bundle_digest=bundle.digest,
            evidence_ref=document.evidence_ref,
            item_digest=entry.item_digest,
            source_revision=entry.source_revision,
            principal_ref=result.principal_ref,
            principal_scope_digest=context.authenticated_context.principal_scope_digest,
            access_context=expected_access,
            redaction_summary=entry.redaction_summary,
        )
        if ref not in seen:
            citations.append(Citation(kind=CitationKind.KNOWLEDGE, ref=ref))
            seen.add(ref)
    if not citations:
        return _held("document_evidence_missing", bundle.bundle_id)
    return GovernedKnowledgeEvidenceResult(
        citations=tuple(citations),
        bundle_id=bundle.bundle_id,
    )


def governed_access_binding(context: GovernedKnowledgeEvidenceContext) -> dict[str, object]:
    """Return the canonical principal, access, purpose, scope, and cutoff binding."""

    access = context.access_context
    request = context.read_request
    return {
        "principal_ref": context.authenticated_context.principal_ref,
        "principal_scope_digest": context.authenticated_context.principal_scope_digest,
        "purpose": request.purpose,
        "scope": tuple(sorted(set(request.scope))),
        "collection_id": access.collection_id,
        "access_context_ref": access.access_context_ref,
        "allowed_access_refs": tuple(sorted(access.allowed_access_refs)),
        "actor_groups": tuple(sorted(access.actor_groups)),
        "evidence_cutoff": request.cutoff.astimezone(UTC).isoformat(),
    }


def governed_evidence_digest(value: object) -> str:
    """Return a canonical opaque SHA-256 identity for governed evidence."""

    payload = value if isinstance(value, str) else canonical_json(value)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _opaque_knowledge_ref(**binding: object) -> str:
    return f"knowledge:{governed_evidence_digest(binding)}"


def _held(reason: str, bundle_id: str | None = None) -> GovernedKnowledgeEvidenceResult:
    return GovernedKnowledgeEvidenceResult(
        hold_reasons=(reason,),
        bundle_id=bundle_id,
    )


__all__: Sequence[str] = (
    "GovernedDocumentAccessContext",
    "GovernedDocumentEvidenceReader",
    "GovernedDocumentRevision",
    "GovernedKnowledgeEvidenceContext",
    "GovernedKnowledgeEvidenceGatherer",
    "GovernedKnowledgeEvidenceHoldError",
    "GovernedKnowledgeEvidenceResult",
)
