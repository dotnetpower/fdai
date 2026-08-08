"""Cross-format golden tests for document ontology distillation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fdai.rule_catalog.pipeline.distill.ontology_claims import claim_text_records
from fdai.rule_catalog.pipeline.distill.ontology_evaluation import (
    ExpectedOntologyFact,
    evaluate_review_package,
    normalize_review_package,
)
from fdai.rule_catalog.pipeline.distill.ontology_ingestion import (
    manual_document_from_envelope,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import AuthorityClass
from fdai.rule_catalog.pipeline.distill.ontology_review import (
    build_ontology_review_package,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityRecord,
    LinkDeclaration,
    SourceAuthorityPolicy,
    VerificationContext,
    proposal_fact_key,
    proposal_value_digest,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
    StructuralUnit,
)
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    DistilledCandidate,
    ManualDocument,
)
from fdai.shared.providers.local.document_ingestion import StandardLibraryDocumentExtractor

from tests.rule_catalog.pipeline.distill.golden_document_corpus import (
    CLAIMS,
    GoldenDocument,
    golden_documents,
)

_RELEASE = "a" * 64


class _GoldenOcr:
    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        assert version.media_type == "application/pdf"
        assert content.startswith(b"%PDF-")
        return tuple(
            StructuralUnit(
                unit_id=f"ocr-{index}",
                kind="page",
                locator=f"page:1:line:{index}",
                text=claim,
            )
            for index, claim in enumerate(CLAIMS, start=1)
        )


class _GoldenDistiller:
    async def distill(self, document: ManualDocument) -> DistillationResult:
        lines = document.text.splitlines()
        bodies = (
            {
                "operation": "update",
                "target_type": "BusinessService",
                "target_identity": "service:checkout",
                "authority": "declared_intent",
                "source_assertion": CLAIMS[0],
                "properties": {"owner_ref": "team:platform"},
            },
            {
                "operation": "add",
                "target_type": "service_depends_on",
                "target_identity": "link:checkout-billing",
                "authority": "declared_intent",
                "source_assertion": CLAIMS[1],
                "properties": {},
                "from_identity": "service:checkout",
                "to_identity": "service:billing",
            },
            {
                "operation": "update",
                "target_type": "ServiceObjective",
                "target_identity": "objective:checkout-latency",
                "authority": "declared_intent",
                "source_assertion": CLAIMS[2],
                "properties": {"comparison": "<", "target_ms": 250, "unit": "ms"},
            },
            {
                "operation": "remove",
                "target_type": "service_depends_on",
                "target_identity": "link:checkout-legacy",
                "authority": "declared_intent",
                "source_assertion": CLAIMS[3],
                "properties": {"constraint": "not"},
                "from_identity": "service:checkout",
                "to_identity": "service:legacy",
            },
        )
        kinds = (
            CandidateKind.ONTOLOGY_OBJECT,
            CandidateKind.ONTOLOGY_LINK,
            CandidateKind.ONTOLOGY_OBJECT,
            CandidateKind.ONTOLOGY_LINK,
        )
        return DistillationResult(
            candidates=tuple(
                DistilledCandidate(
                    kind=kinds[index],
                    candidate_id=f"candidate-{index + 1}",
                    source_ref=document.source_ref,
                    source_section="Synthetic corpus",
                    source_lines=(
                        next(
                            line_number
                            for line_number, line in enumerate(lines, start=1)
                            if CLAIMS[index] in line
                        ),
                    )
                    * 2,
                    content_sha=document.content_sha,
                    body=body,
                )
                for index, body in enumerate(bodies)
            )
        )


async def test_formats_produce_equivalent_claims_proposals_and_graph() -> None:
    projections = []
    for index, golden in enumerate(golden_documents(), start=1):
        envelope = await _extract(golden, identity=index)
        document = manual_document_from_envelope(envelope)
        result = await _GoldenDistiller().distill(document)
        context = _context(document.source_ref)
        package = build_ontology_review_package(
            document=document,
            result=result,
            context=context,
            extraction_run_id="golden-run",
        )
        replay = build_ontology_review_package(
            document=document,
            result=result,
            context=context,
            extraction_run_id="golden-run",
        )

        assert package.package_digest == replay.package_digest
        assert package.summary.total_claims == 4
        assert package.summary.critical_claims == 4
        assert package.summary.mapped_claims == 4
        assert package.summary.unresolved_claims == 0
        assert package.summary.denied_proposals == 0
        assert _citation_errors(package, document) == 0

        expected = tuple(
            ExpectedOntologyFact(
                proposal.proposal.claim_id,
                proposal_fact_key(proposal.proposal),
                proposal_value_digest(proposal.proposal),
                True,
            )
            for proposal in package.proposals
        )
        report = evaluate_review_package(package, expected)
        assert report.critical_claim_recall >= 0.98
        assert report.precision >= 0.98
        assert report.semantic_review_count == 0
        projections.append(normalize_review_package(package))

    assert len(set(projections)) == 1


async def _extract(golden: GoldenDocument, *, identity: int):
    digest = hashlib.sha256(golden.content).hexdigest()
    now = datetime(2026, 8, 3, tzinfo=UTC)
    version = DocumentVersion(
        document_id=UUID(int=identity),
        version_id=UUID(int=identity + 100),
        upload_id=UUID(int=identity + 200),
        source_name=golden.name,
        source_sha256=digest,
        size_bytes=len(golden.content),
        media_type=golden.media_type,
        observed_format=golden.observed_format,
        state=DocumentState.EXTRACTING,
        protection_state=ProtectionState.NONE,
        access=AccessDescriptor(reference="access:golden", collection_id="golden"),
        retention=RetentionPolicy(policy_version="v1"),
        purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
        uploader_id="synthetic",
        created_at=now,
        updated_at=now,
    )

    async def chunks():
        yield golden.content

    extractor = StandardLibraryDocumentExtractor(image_ocr=_GoldenOcr() if golden.scanned else None)
    return await extractor.extract(version=version, chunks=chunks())


def _context(source_ref: str) -> VerificationContext:
    return VerificationContext(
        ontology_release=_RELEASE,
        current_graph_revision="graph-1",
        object_types=frozenset({"BusinessService", "ServiceObjective"}),
        links=(LinkDeclaration("service_depends_on", "BusinessService", "BusinessService"),),
        entities=(
            EntityRecord("service:checkout", "BusinessService"),
            EntityRecord("service:billing", "BusinessService"),
            EntityRecord("service:legacy", "BusinessService"),
            EntityRecord("objective:checkout-latency", "ServiceObjective"),
        ),
        source_policies=(
            SourceAuthorityPolicy(
                source_ref,
                frozenset({AuthorityClass.DECLARED_INTENT}),
                10,
            ),
        ),
        claim_text=(),
    )


def _citation_errors(package, document: ManualDocument) -> int:
    provenance = {item.line_number: item for item in document.line_provenance}
    claim_text = dict(claim_text_records(document, package.claims))
    errors = 0
    for claim in package.claims:
        evidence = claim.evidence
        item = provenance.get(evidence.line_start)
        if item is None:
            errors += 1
            continue
        if (
            item.source_format != evidence.source_format
            or item.unit_id != evidence.structural_unit_id
            or item.locator != evidence.structural_locator
            or hashlib.sha256(claim_text[claim.claim_id].encode()).hexdigest()
            != evidence.text_sha256
        ):
            errors += 1
    return errors
