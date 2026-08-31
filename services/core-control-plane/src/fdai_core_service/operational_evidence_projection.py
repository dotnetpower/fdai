"""Bind admitted operational evidence to the Core-to-Operator read projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai.core.operational_context import (
    OperationalEvidencePrincipalContextProvider,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
    project_operational_evidence_read_result,
)
from fdai_service_contracts import OperationalEvidenceProjection


@dataclass(frozen=True, slots=True)
class SemanticOperationalEvidenceReader:
    """Read and validate one exact principal-scoped evidence projection."""

    service: OperationalEvidenceReadService
    principal_contexts: OperationalEvidencePrincipalContextProvider

    async def read(
        self,
        *,
        principal_ref: str,
        principal_scope_digest: str,
        purpose: str,
        ontology_release_digest: str,
        catalog_revision: str,
        scope: tuple[str, ...],
        cutoff: datetime,
    ) -> dict[str, object]:
        """Return an admitted no-authority projection or fail the read closed."""

        request = OperationalEvidenceReadRequest(
            ontology_release_digest=ontology_release_digest,
            catalog_revision=catalog_revision,
            purpose=purpose,
            scope=scope,
            cutoff=cutoff,
        )
        authenticated_context = await self.principal_contexts.context_for(
            request,
            principal_ref=principal_ref,
            principal_scope_digest=principal_scope_digest,
        )
        if (
            authenticated_context.principal_ref != principal_ref
            or authenticated_context.principal_scope_digest != principal_scope_digest
            or authenticated_context.purpose != purpose
        ):
            raise ValueError("operational evidence authenticated principal context does not match")
        result = await self.service.read(
            request,
            authenticated_context=authenticated_context,
        )
        return OperationalEvidenceProjection.model_validate(
            project_operational_evidence_read_result(result)
        ).model_dump(mode="json")


__all__ = ["SemanticOperationalEvidenceReader"]
