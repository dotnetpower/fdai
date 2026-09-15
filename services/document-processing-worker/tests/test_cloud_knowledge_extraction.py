"""A sealed cloud release is inert content, not an instruction or authority grant."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai_document_worker_service.adapters.cloud_knowledge import cloud_reference_units
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
)
from fdai_service_contracts.cloud_knowledge import (
    Applicability,
    CloudSourceEvidence,
    RefreshPolicy,
    SourceCheckReceipt,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_release import (
    CloudKnowledgeDocument,
    KnowledgeReleaseBinding,
    KnowledgeReleaseManifest,
    KnowledgeStructuredReleaseManifest,
    KnowledgeTextReleaseManifest,
    normalized_document,
)
from fdai_service_contracts.cloud_knowledge_structure import (
    CloudArticleBlock,
    CloudStructuredDocument,
    StructuredNormalizerVersion,
    excerpt_digest,
    structured_excerpts,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def release_version() -> tuple[KnowledgeReleaseManifest, DocumentVersion]:
    original = "<main>Raw original</main>"
    text = "# Networking\nPremium only.\n# Exception\nPremium v2 uses other requirements."
    source = CloudSourceEvidence(
        source_id="apim",
        source_url="https://example.com/apim",
        source_sha256=content_digest(original.encode()),
        normalized_sha256=content_digest(text.encode()),
        collected_at=NOW - timedelta(days=44),
        check=SourceCheckReceipt(
            source_id="apim",
            source_url="https://example.com/apim",
            checked_at=NOW - timedelta(days=44),
            content_sha256=content_digest(original.encode()),
            outcome="fetched",
            equivalence="body_hash",
            collector_id="test",
        ),
        applicability=Applicability(
            resource_type="Microsoft.ApiManagement/service",
            service_generation="classic",
            skus=("Premium",),
        ),
        policy=RefreshPolicy(),
        license_ref="fixture",
    )
    release = KnowledgeReleaseManifest(
        release_id="cloud-1",
        sequence=1,
        collection_id="cloud",
        registry_digest="a" * 64,
        package_created_at=NOW,
        expires_at=NOW + timedelta(days=7),
        documents=(
            CloudKnowledgeDocument(
                evidence=source, title="APIM", original_text=original, text=text
            ),
        ),
    )
    binding = KnowledgeReleaseBinding(
        release_id=release.release_id,
        sequence=1,
        manifest_digest=release.digest,
        registry_digest=release.registry_digest,
        package_created_at=NOW,
        imported_at=NOW,
        admission_expires_at=release.expires_at,
        verified_key_id="test",
        sources=(source,),
    )
    version = DocumentVersion(
        document_id=uuid4(),
        version_id=uuid4(),
        upload_id=uuid4(),
        source_name="cloud-1.json",
        source_sha256=release.digest,
        size_bytes=len(canonical_bytes(release)),
        media_type="application/json",
        observed_format="text",
        state=DocumentState.EXTRACTING,
        access=AccessDescriptor(
            reference="collection:cloud",
            collection_id="cloud",
            reader_groups=("operators",),
        ),
        retention=RetentionPolicy(policy_version="test"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE, DocumentPurpose.CLOUD_REFERENCE),
        uploader_id="requester",
        created_at=NOW,
        updated_at=NOW,
        cloud_knowledge=binding,
        protection_state=ProtectionState.NONE,
    )
    return release, version


def test_source_sections_preserve_conditions_without_indexing_original_html() -> None:
    release, version = release_version()
    units = cloud_reference_units(version, canonical_bytes(release))
    assert len(units) == 2
    assert all("Generation: classic; SKU: Premium" in unit.text for unit in units)
    assert all(
        "Raw original" not in unit.text and "registry_digest" not in unit.text for unit in units
    )
    assert "Premium v2" in units[1].text
    assert len({unit.unit_id for unit in units}) == len(units)
    assert version.cloud_knowledge is not None
    assert version.cloud_knowledge.sources[0].collected_at == NOW - timedelta(days=44)


def test_normalized_only_v2_extracts_identical_units_without_original_bytes() -> None:
    legacy, version = release_version()
    compact = KnowledgeTextReleaseManifest.model_validate(
        legacy.model_dump(exclude={"schema_version", "reader_version", "documents"})
        | {"documents": tuple(normalized_document(document) for document in legacy.documents)}
    )
    content = canonical_bytes(compact)
    assert b"original_text" not in content and b"Raw original" not in content
    assert version.cloud_knowledge is not None
    binding = version.cloud_knowledge.model_copy(update={"manifest_digest": compact.digest})
    compact_version = version.model_copy(
        update={
            "cloud_knowledge": binding,
            "source_sha256": compact.digest,
            "size_bytes": len(content),
        }
    )
    assert cloud_reference_units(compact_version, content) == cloud_reference_units(
        version, canonical_bytes(legacy)
    )
    assert binding.sources == version.cloud_knowledge.sources


def test_swapped_payload_or_unsigned_binding_never_extracts() -> None:
    release, version = release_version()
    with pytest.raises(ValueError):
        cloud_reference_units(version, canonical_bytes(release) + b" ")
    with pytest.raises(ValueError):
        cloud_reference_units(
            version.model_copy(update={"cloud_knowledge": None}),
            canonical_bytes(release),
        )
    altered = release.model_copy(update={"collection_id": "other"})
    with pytest.raises(ValueError):
        cloud_reference_units(version, canonical_bytes(altered))


@pytest.mark.parametrize("normalizer", ["2.0.0", "2.1.0"])
def test_worker_preserves_both_structured_reader_generations(
    normalizer: StructuredNormalizerVersion,
) -> None:
    legacy, version = release_version()
    source = legacy.documents[0]
    doc = CloudStructuredDocument(
        evidence=source.evidence,
        title=source.title,
        text=source.text,
        normalizer_version=normalizer,
        derived_at=NOW,
        blocks=(
            CloudArticleBlock(block_id="body", kind="paragraph", start=0, end=len(source.text)),
        ),
    )
    manifest = KnowledgeStructuredReleaseManifest.model_validate(
        legacy.model_dump(exclude={"schema_version", "reader_version", "documents"})
        | {
            "reader_version": "3.1.0" if normalizer == "2.1.0" else "3.0.0",
            "documents": (doc,),
            "excerpt_digests": (excerpt_digest(doc),),
        }
    )
    assert version.cloud_knowledge is not None
    binding = version.cloud_knowledge.model_copy(
        update={"manifest_digest": manifest.digest, "processing_digests": (doc.processing_digest,)}
    )
    content = canonical_bytes(manifest)
    structured_version = version.model_copy(
        update={
            "cloud_knowledge": binding,
            "source_sha256": manifest.digest,
            "size_bytes": len(content),
        }
    )
    units = cloud_reference_units(structured_version, content)
    assert tuple(unit.text for unit in units) == tuple(
        item.text for item in structured_excerpts(doc)
    )
    wrong = structured_version.model_copy(
        update={"cloud_knowledge": binding.model_copy(update={"processing_digests": ("f" * 64,)})}
    )
    with pytest.raises(ValueError):
        cloud_reference_units(wrong, content)


@pytest.mark.parametrize("paragraph", ["a" * 9000, "가" * 3000])
def test_oversize_sections_are_held_instead_of_detaching_table_context(paragraph: str) -> None:
    release, version = release_version()
    document = release.documents[0]
    text = (
        "# Table conditions\n| SKU | Port |\n| Premium | 443 |\n"
        + paragraph
        + "\nFootnote: exception."
    )
    evidence = document.evidence.model_copy(
        update={"normalized_sha256": content_digest(text.encode())}
    )
    document = document.model_copy(update={"evidence": evidence, "text": text})
    release = release.model_copy(update={"documents": (document,)})
    binding = version.cloud_knowledge.model_copy(
        update={
            "manifest_digest": release.digest,
            "sources": (evidence,),
        }
    )
    version = version.model_copy(
        update={"cloud_knowledge": binding, "source_sha256": release.digest}
    )
    with pytest.raises(ValueError, match="safe excerpt byte limit"):
        cloud_reference_units(version, canonical_bytes(release))


@pytest.mark.parametrize("days", [0, 6, 7, 10, -1])
async def test_cloud_reference_scanner_database_age_is_independent_of_package_age(
    days: int,
) -> None:
    from unittest.mock import AsyncMock

    from fdai_document_worker_service.adapters.processing import (
        ClamAvMalwareScanner,
        ClamAvScannerConfig,
    )

    scanner = ClamAvMalwareScanner(config=ClamAvScannerConfig())
    local_timestamp = (NOW - timedelta(days=days)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
    scanner._command = AsyncMock(return_value=f"ClamAV 1.4/12345/{local_timestamp}\0")
    if days < 0 or days >= 7:
        with pytest.raises(ValueError, match="stale or future"):
            await scanner.verify_database_freshness(NOW)
    else:
        await scanner.verify_database_freshness(NOW)
