"""Bounded runtime read composition for operational evidence bundles."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.shared.contracts.models import Autonomy

from .console_projection import SecuredContextResult, project_context_snapshot
from .evidence_bundle import ReceiptValidator, build_operational_evidence_bundle
from .evidence_bundle_identity import bundle_body
from .evidence_bundle_models import (
    CatalogEvidenceItem,
    ClaimRecord,
    DocumentEvidenceExcerpt,
    OntologyEvidenceItem,
    OperationalEvidenceBundle,
    StateEvidenceItem,
    canonical_json,
)
from .models import OperationalContextSnapshot
from .principal_context import AuthenticatedPrincipalContext


@dataclass(frozen=True, slots=True)
class OperationalEvidenceReadRequest:
    """Server-grounded identity for one principal-scoped evidence read."""

    ontology_release_digest: str
    catalog_revision: str
    purpose: str
    scope: tuple[str, ...]
    cutoff: datetime

    def __post_init__(self) -> None:
        if not self.ontology_release_digest.startswith("sha256:"):
            raise ValueError("evidence read release MUST be a SHA-256 digest")
        if not self.catalog_revision.strip() or not self.purpose.strip():
            raise ValueError("evidence read catalog revision and purpose MUST be non-empty")
        if not self.scope or any(not item.strip() for item in self.scope):
            raise ValueError("evidence read scope MUST be non-empty")
        if self.cutoff.tzinfo is None or self.cutoff.utcoffset() is None:
            raise ValueError("evidence read cutoff MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class OperationalEvidenceMaterial:
    """Typed authority-lane material collected for one exact read identity."""

    ontology_release_digest: str
    catalog_revision: str
    purpose: str
    scope: tuple[str, ...]
    cutoff: datetime
    claims: tuple[ClaimRecord, ...] = ()
    ontology: tuple[OntologyEvidenceItem, ...] = ()
    state: tuple[StateEvidenceItem, ...] = ()
    catalog: tuple[CatalogEvidenceItem, ...] = ()
    documents: tuple[DocumentEvidenceExcerpt, ...] = ()
    context_snapshot: OperationalContextSnapshot | None = None
    secured_context_result: SecuredContextResult | None = None


class OperationalEvidenceSource(Protocol):
    """Collect typed evidence lanes without deciding or granting authority."""

    async def collect(
        self,
        request: OperationalEvidenceReadRequest,
    ) -> OperationalEvidenceMaterial: ...


@dataclass(frozen=True, slots=True)
class OperationalEvidenceReadResult:
    """Read-only bundle response with explicit absence of mutation authority."""

    bundle: OperationalEvidenceBundle
    principal_ref: str
    context_metadata: dict[str, object] | None = None
    execution_authority: bool = False
    mutation_authority: bool = False


class OperationalEvidenceReadService:
    """Rebuild one bounded source response under server-owned read limits."""

    def __init__(
        self,
        *,
        source: OperationalEvidenceSource,
        clock: Callable[[], datetime],
        max_items: int = 256,
        max_bytes: int = 1_048_576,
        receipt_validator: ReceiptValidator | None = None,
    ) -> None:
        if not 1 <= max_items <= 2_048 or not 1 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError("operational evidence read limits are out of bounds")
        self._source = source
        self._clock = clock
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._receipt_validator = receipt_validator

    async def read(
        self,
        request: OperationalEvidenceReadRequest,
        *,
        authenticated_context: AuthenticatedPrincipalContext,
    ) -> OperationalEvidenceReadResult:
        """Collect and rebuild one exact read; mismatched source identity fails closed."""

        if request.purpose != authenticated_context.purpose:
            raise ValueError("evidence read purpose does not match authenticated context")
        material = await self._source.collect(request)
        expected = (
            request.ontology_release_digest,
            request.catalog_revision,
            request.purpose,
            tuple(sorted(set(request.scope))),
            request.cutoff,
        )
        actual = (
            material.ontology_release_digest,
            material.catalog_revision,
            material.purpose,
            tuple(sorted(set(material.scope))),
            material.cutoff,
        )
        if actual != expected:
            raise ValueError("operational evidence source identity does not match the read request")
        recorded_at = self._clock()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("operational evidence read clock MUST be timezone-aware")
        if (material.context_snapshot is None) != (material.secured_context_result is None):
            raise ValueError("operational context metadata requires both snapshot and receipt")
        context_metadata = None
        if material.context_snapshot is not None and material.secured_context_result is not None:
            _bind_context_to_read_request(
                request=request,
                context_snapshot=material.context_snapshot,
                secured_context_result=material.secured_context_result,
            )
            context_metadata = project_context_snapshot(
                snapshot=material.context_snapshot,
                secured_result=material.secured_context_result,
                authenticated_context=authenticated_context,
            )
        bundle_max_bytes = self._max_bytes - _response_overhead(
            context_metadata,
            principal_ref=authenticated_context.principal_ref,
        )
        if bundle_max_bytes < 1:
            raise ValueError("operational evidence response exceeds max_bytes")
        bundle = build_operational_evidence_bundle(
            cutoff=request.cutoff,
            trusted_recorded_at=recorded_at,
            ontology_release_digest=request.ontology_release_digest,
            catalog_revision=request.catalog_revision,
            purpose=request.purpose,
            scope=request.scope,
            claims=material.claims,
            ontology=material.ontology,
            state=material.state,
            catalog=material.catalog,
            documents=material.documents,
            max_items=self._max_items,
            max_bytes=bundle_max_bytes,
            autonomy_ceiling=Autonomy.SHADOW_ONLY,
            receipt_validator=self._receipt_validator,
        )
        result = OperationalEvidenceReadResult(
            bundle=bundle,
            principal_ref=authenticated_context.principal_ref,
            context_metadata=context_metadata,
        )
        if (
            _serialized_response_size(
                bundle,
                context_metadata,
                principal_ref=result.principal_ref,
                execution_authority=result.execution_authority,
                mutation_authority=result.mutation_authority,
            )
            > self._max_bytes
        ):
            raise ValueError("operational evidence response exceeds max_bytes")
        return result


__all__: Sequence[str] = (
    "OperationalEvidenceMaterial",
    "OperationalEvidenceReadRequest",
    "OperationalEvidenceReadResult",
    "OperationalEvidenceReadService",
    "OperationalEvidenceSource",
)


def _serialized_response_size(
    bundle: OperationalEvidenceBundle,
    context_metadata: dict[str, object] | None,
    *,
    principal_ref: str,
    execution_authority: bool = False,
    mutation_authority: bool = False,
) -> int:
    """Return canonical bytes for the complete response, including Context metadata."""

    body = {
        "bundle": bundle_body(
            cutoff=bundle.cutoff,
            trusted_recorded_at=bundle.trusted_recorded_at,
            ontology_release_digest=bundle.ontology_release_digest,
            catalog_revision=bundle.catalog_revision,
            purpose=bundle.purpose,
            scope=bundle.scope,
            claims=bundle.claims,
            ontology=bundle.ontology,
            state=bundle.state,
            catalog=bundle.catalog,
            documents=bundle.documents,
            citation_manifest=bundle.citation_manifest,
            conflicts=bundle.conflicts,
            missing_paths=bundle.missing_paths,
            evidence_issues=bundle.evidence_issues,
            hold_reasons=bundle.hold_reasons,
            max_items=bundle.max_items,
            max_bytes=bundle.max_bytes,
            used_items=bundle.used_items,
            used_bytes=bundle.used_bytes,
            autonomy_ceiling=bundle.autonomy_ceiling,
        ),
        "context_metadata": context_metadata,
        "principal_ref": principal_ref,
        "execution_authority": execution_authority,
        "mutation_authority": mutation_authority,
    }
    return len(canonical_json(body).encode("utf-8"))


def _response_overhead(
    context_metadata: dict[str, object] | None,
    *,
    principal_ref: str,
) -> int:
    empty_bundle = canonical_json({})
    response = canonical_json(
        {
            "bundle": {},
            "context_metadata": context_metadata,
            "principal_ref": principal_ref,
            "execution_authority": False,
            "mutation_authority": False,
        }
    )
    return len(response.encode("utf-8")) - len(empty_bundle.encode("utf-8"))


def _bind_context_to_read_request(
    *,
    request: OperationalEvidenceReadRequest,
    context_snapshot: OperationalContextSnapshot,
    secured_context_result: SecuredContextResult,
) -> None:
    """Fail closed unless the Context snapshot and receipt match this exact read."""

    context_release_digest = dict(context_snapshot.catalog_versions).get("ontology")
    if context_release_digest != request.ontology_release_digest:
        raise ValueError(
            "operational context snapshot release does not match the evidence read request"
        )
    if _utc(context_snapshot.cutoff) != _utc(request.cutoff):
        raise ValueError(
            "operational context snapshot cutoff does not match the evidence read request"
        )
    if context_snapshot.target_resource_id not in request.scope:
        raise ValueError(
            "operational context snapshot target does not match the evidence read request scope"
        )
    receipt = secured_context_result.receipt
    if receipt.ontology_release.digest != request.ontology_release_digest:
        raise ValueError("secured Context receipt release does not match the evidence read request")
    if _utc(receipt.observation_cutoff) != _utc(request.cutoff):
        raise ValueError("secured Context receipt cutoff does not match the evidence read request")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("operational evidence read timestamps MUST be timezone-aware")
    return value.astimezone(UTC)
