"""Bridge governed document envelopes into review-only ontology distillation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from fdai.rule_catalog.pipeline.distill.ontology_council import OntologyAwareDistiller
from fdai.rule_catalog.pipeline.distill.ontology_models import stable_digest
from fdai.rule_catalog.pipeline.distill.ontology_review import (
    OntologyReviewPackage,
    build_ontology_review_package,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import VerificationContext
from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    ProtectionState,
    UploadSession,
)
from fdai.shared.providers.distiller import (
    Distiller,
    ManualDocument,
    ManualLineProvenance,
)

_EXTRACTABLE_PROTECTION = frozenset(
    {
        ProtectionState.NONE,
        ProtectionState.LABELED_UNENCRYPTED,
        ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
    }
)
_WHITESPACE = re.compile(r"\s+")


@runtime_checkable
class OntologyReviewPackageSink(Protocol):
    """Persist one inert review package without projecting graph changes."""

    async def put(self, package: OntologyReviewPackage) -> None: ...


def manual_document_from_envelope(envelope: DocumentEnvelope) -> ManualDocument:
    """Create one replay-stable manual line per cited structural unit."""
    if envelope.protection_state not in _EXTRACTABLE_PROTECTION:
        raise ValueError("ontology distillation requires extractable document protection")
    unit_ids = [unit.unit_id for unit in envelope.units]
    locators = [unit.locator for unit in envelope.units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("document envelope unit ids MUST be unique")
    if len(locators) != len(set(locators)):
        raise ValueError("document envelope locators MUST be unique")

    lines: list[str] = []
    provenance: list[ManualLineProvenance] = []
    for unit in envelope.units:
        text = _WHITESPACE.sub(" ", unit.text).strip()
        if not text:
            continue
        lines.append(text)
        provenance.append(
            ManualLineProvenance(
                line_number=len(lines),
                source_format=envelope.observed_format,
                unit_id=unit.unit_id,
                locator=unit.locator,
            )
        )
    if not lines:
        raise ValueError("ontology distillation requires at least one extracted text unit")

    normalized_text = "\n".join(lines)
    source_ref = f"document://{envelope.document_id}/versions/{envelope.version_id}"
    return ManualDocument(
        doc_id=str(envelope.document_id),
        text=normalized_text,
        source_ref=source_ref,
        content_sha=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        metadata={
            "revision": str(envelope.version_id),
            "access_policy_ref": envelope.access_descriptor_ref,
            "source_format": envelope.observed_format,
            "source_sha256": envelope.source_sha256,
            "extractor": f"{envelope.extractor_name}:{envelope.extractor_version}",
        },
        line_provenance=tuple(provenance),
    )


class EnvelopeOntologyReviewConsumer:
    """Build and store a review package for an admitted manual-distillation upload."""

    purpose = DocumentPurpose.MANUAL_DISTILLATION

    def __init__(
        self,
        *,
        distiller: Distiller | OntologyAwareDistiller,
        context_provider: Callable[[DocumentEnvelope], VerificationContext],
        sink: OntologyReviewPackageSink,
    ) -> None:
        self._distiller = distiller
        self._context_provider = context_provider
        self._sink = sink

    async def consume(
        self,
        *,
        session: UploadSession,
        envelope: DocumentEnvelope,
    ) -> tuple[str, ...]:
        del session
        document = manual_document_from_envelope(envelope)
        context = self._context_provider(envelope)
        if isinstance(self._distiller, OntologyAwareDistiller):
            result = await self._distiller.distill_ontology(document, context)
        else:
            result = await self._distiller.distill(document)
        extraction_run_id = "run-" + stable_digest(
            {
                "document_id": str(envelope.document_id),
                "version_id": str(envelope.version_id),
                "source_sha256": envelope.source_sha256,
                "normalized_sha256": document.content_sha,
                "extractor_name": envelope.extractor_name,
                "extractor_version": envelope.extractor_version,
                "ontology_release": context.ontology_release,
                "graph_revision": context.current_graph_revision,
            }
        )
        package = build_ontology_review_package(
            document=document,
            result=result,
            context=context,
            extraction_run_id=extraction_run_id,
        )
        await self._sink.put(package)
        return ()


__all__ = [
    "EnvelopeOntologyReviewConsumer",
    "OntologyReviewPackageSink",
    "manual_document_from_envelope",
]
