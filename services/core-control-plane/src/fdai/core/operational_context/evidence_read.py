"""Bounded runtime read composition for operational evidence bundles."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.shared.contracts.models import Autonomy

from .console_projection import SecuredContextResult, project_context_snapshot
from .evidence_bundle import ReceiptValidator, build_operational_evidence_bundle
from .evidence_bundle_models import (
    CatalogEvidenceItem,
    ClaimRecord,
    DocumentEvidenceExcerpt,
    OntologyEvidenceItem,
    OperationalEvidenceBundle,
    StateEvidenceItem,
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
            max_bytes=self._max_bytes,
            autonomy_ceiling=Autonomy.SHADOW_ONLY,
            receipt_validator=self._receipt_validator,
        )
        if (material.context_snapshot is None) != (material.secured_context_result is None):
            raise ValueError("operational context metadata requires both snapshot and receipt")
        context_metadata = None
        if material.context_snapshot is not None and material.secured_context_result is not None:
            context_metadata = project_context_snapshot(
                snapshot=material.context_snapshot,
                secured_result=material.secured_context_result,
                authenticated_context=authenticated_context,
            )
        return OperationalEvidenceReadResult(
            bundle=bundle,
            principal_ref=authenticated_context.principal_ref,
            context_metadata=context_metadata,
        )


__all__: Sequence[str] = (
    "OperationalEvidenceMaterial",
    "OperationalEvidenceReadRequest",
    "OperationalEvidenceReadResult",
    "OperationalEvidenceReadService",
    "OperationalEvidenceSource",
)
