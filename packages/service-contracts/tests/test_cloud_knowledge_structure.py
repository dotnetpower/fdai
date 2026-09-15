"""Structured releases preserve signed history and cannot manufacture context or freshness."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_service_contracts.cloud_knowledge import (
    Applicability,
    CloudKnowledgeSource,
    CloudSourceEvidence,
    RefreshPolicy,
    SourceCheckReceipt,
    SourceRegistryRevision,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_package import (
    KnowledgePackageError,
    KnowledgeTrustedKey,
    KnowledgeTrustPolicy,
    sign_release,
    verify_package,
)
from fdai_service_contracts.cloud_knowledge_release import (
    KnowledgeReleaseBinding,
    KnowledgeStructuredReleaseManifest,
    parse_knowledge_manifest,
)
from fdai_service_contracts.cloud_knowledge_structure import (
    CloudArticleBlock,
    CloudArticleLink,
    CloudStructuredDocument,
    excerpt_digest,
    structured_excerpts,
)
from fdai_service_contracts.cloud_knowledge_updates import source_update_pending

NOW = datetime(2026, 9, 15, tzinfo=UTC)


def document() -> CloudStructuredDocument:
    text = "443 | Premium\n\nOnly the named generation is supported."
    source_hash = content_digest(b"retained original")
    evidence = CloudSourceEvidence(
        source_id="network",
        source_url="https://example.com/network",
        source_sha256=source_hash,
        normalized_sha256=content_digest(text.encode()),
        collected_at=NOW - timedelta(days=1),
        check=SourceCheckReceipt(
            source_id="network",
            source_url="https://example.com/network",
            checked_at=NOW - timedelta(hours=1),
            content_sha256=source_hash,
            outcome="unchanged",
            equivalence="body_hash",
            collector_id="fixture",
        ),
        applicability=Applicability(
            resource_type="Microsoft.Network/virtualNetworks", service_generation="reference"
        ),
        license_ref="fixture",
        policy=RefreshPolicy(),
    )
    return CloudStructuredDocument(
        evidence=evidence,
        title="Network",
        text=text,
        derived_at=NOW,
        blocks=(
            CloudArticleBlock(
                block_id="row",
                kind="table_row",
                start=0,
                end=13,
                table_id="ports",
                table_header="Port | SKU",
                heading_path=("Network",),
            ),
            CloudArticleBlock(
                block_id="note",
                kind="notice",
                start=15,
                end=len(text),
                heading_path=("Exceptions",),
            ),
        ),
        required_context_ids=("note",),
        links=(
            CloudArticleLink(
                block_id="row", label="Reference", target="https://example.com/reference"
            ),
        ),
    )


def release() -> tuple[
    KnowledgeStructuredReleaseManifest,
    SourceRegistryRevision,
    KnowledgeTrustPolicy,
    Ed25519PrivateKey,
]:
    doc = document()
    source = CloudKnowledgeSource(
        source_id="network",
        collection_id="network",
        url=doc.evidence.source_url,
        title=doc.title,
        applicability=doc.evidence.applicability,
        storage_allowed=True,
        internal_transfer_allowed=True,
        license_ref="fixture",
    )
    registry = SourceRegistryRevision(
        revision=1, approved_by="reviewer", valid_until=NOW + timedelta(days=7), sources=(source,)
    )
    key = Ed25519PrivateKey.generate()
    trust = KnowledgeTrustPolicy(
        approved_by="independent-reviewer",
        valid_from=NOW - timedelta(days=2),
        valid_until=NOW + timedelta(days=7),
        revocation_checked_at=NOW,
        keys=(
            KnowledgeTrustedKey(
                key_id="fixture",
                public_key=key.public_key().public_bytes_raw().hex(),
                valid_from=NOW - timedelta(days=2),
                valid_until=NOW + timedelta(days=7),
            ),
        ),
    )
    manifest = KnowledgeStructuredReleaseManifest(
        release_id="network-1",
        sequence=1,
        collection_id="network",
        registry_digest=registry.digest,
        package_created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        documents=(doc,),
        excerpt_digests=(excerpt_digest(doc),),
    )
    return manifest, registry, trust, key


def test_complete_structured_package_roundtrip_and_original_exclusion() -> None:
    manifest, registry, trust, key = release()
    wire = sign_release(manifest, key_id="fixture", private_key=key)
    verified = verify_package(wire, registry=registry, trust=trust, now=NOW)
    assert verified.manifest == manifest
    assert parse_knowledge_manifest(verified.content) == manifest
    assert verified.binding.processing_digests == (manifest.documents[0].processing_digest,)
    assert b'"original_text"' not in wire
    assert b"retained original" not in wire


def test_table_caveat_and_link_are_complete_in_each_evidence_bundle() -> None:
    doc = document()
    excerpts = structured_excerpts(doc)
    assert len(excerpts) == 2
    assert "Port | SKU" in excerpts[0].text
    assert "Only the named generation" in excerpts[0].text
    assert "https://example.com/reference" in excerpts[0].text
    assert all(len(item.text.encode()) <= 8192 for item in excerpts)
    assert structured_excerpts(doc) == excerpts


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_text", "forbidden"),
        ("original_text", None),
        ("recipe", "executable"),
        ("recipe_digest", "f" * 64),
        ("required_context_ids", ("absent",)),
    ],
)
def test_closed_structure_rejects_unknown_and_unbound_content(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        CloudStructuredDocument.model_validate(document().model_dump() | {field: value})


@pytest.mark.parametrize("span", [(1, 13), (0, 12), (0, 9000)])
def test_structure_rejects_gaps_overlap_or_truncation(span: tuple[int, int]) -> None:
    values = document().model_dump()
    values["blocks"][0]["start"], values["blocks"][0]["end"] = span
    with pytest.raises(ValueError, match="article"):
        CloudStructuredDocument.model_validate(values)


def test_recipes_and_derivation_do_not_renew_source_observations() -> None:
    doc = document()
    later = CloudStructuredDocument.model_validate(
        doc.model_dump() | {"derived_at": NOW + timedelta(days=1)}
    )
    assert later.processing_digest == doc.processing_digest
    assert later.evidence == doc.evidence
    newer_check = doc.evidence.check.model_copy(update={"checked_at": NOW})
    newer = CloudStructuredDocument.model_validate(
        doc.model_dump()
        | {"evidence": doc.evidence.model_dump() | {"check": newer_check.model_dump()}}
    )
    assert newer.processing_digest == doc.processing_digest
    assert newer.evidence.collected_at == doc.evidence.collected_at


def test_pending_change_uses_processing_not_only_original_or_check_time() -> None:
    manifest, registry, trust, key = release()
    verified = verify_package(
        sign_release(manifest, key_id="fixture", private_key=key),
        registry=registry,
        trust=trust,
        now=NOW,
    )
    doc = document()
    assert not source_update_pending(verified.binding, doc.evidence, doc.evidence, doc)
    altered = CloudStructuredDocument.model_validate(
        doc.model_dump() | {"required_context_ids": ()}
    )
    assert source_update_pending(verified.binding, doc.evidence, doc.evidence, altered)
    assert source_update_pending(verified.binding, doc.evidence, doc.evidence)


def test_new_raw_body_cannot_be_hidden_by_an_old_structured_checkpoint() -> None:
    manifest, registry, trust, key = release()
    verified = verify_package(
        sign_release(manifest, key_id="fixture", private_key=key),
        registry=registry,
        trust=trust,
        now=NOW,
    )
    doc = document()
    digest = content_digest(b"new source revision")
    candidate = CloudSourceEvidence.model_validate(
        doc.evidence.model_dump()
        | {
            "source_sha256": digest,
            "check": doc.evidence.check.model_dump() | {"content_sha256": digest},
        }
    )
    assert source_update_pending(verified.binding, doc.evidence, candidate, doc)


def test_one_unresolved_dependency_rejects_the_complete_generation() -> None:
    doc = document().model_copy(update={"unresolved_dependencies": ("missing_diagram",)})
    with pytest.raises(ValueError, match="unresolved"):
        structured_excerpts(doc)


def test_global_context_cannot_hide_another_required_dependency() -> None:
    values = document().model_dump()
    values["blocks"][0]["context_ids"] = ("note",)
    values["required_context_ids"] = ("row",)
    with pytest.raises(ValueError, match="recursive"):
        CloudStructuredDocument.model_validate(values)


def test_required_context_expansion_has_an_aggregate_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fdai_service_contracts.cloud_knowledge_structure as structure

    monkeypatch.setattr(structure, "MAX_DERIVED_BYTES", 300, raising=False)
    with pytest.raises(ValueError, match="aggregate"):
        structured_excerpts(document())


def test_signature_covers_context_and_version_pair() -> None:
    import json

    manifest, registry, trust, key = release()
    wire = sign_release(manifest, key_id="fixture", private_key=key)
    data = json.loads(wire)
    data["schema_version"] = "fdai.cloud-knowledge-package.v2"
    content = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    with pytest.raises(KnowledgePackageError):
        verify_package(content, registry=registry, trust=trust, now=NOW)
    broken = manifest.model_copy(update={"excerpt_digests": ("0" * 64,)})
    with pytest.raises(KnowledgePackageError):
        sign_release(broken, key_id="fixture", private_key=key)


def test_legacy_binding_serialization_has_no_new_processing_field() -> None:
    manifest, _, _, _ = release()
    binding = KnowledgeReleaseBinding(
        release_id=manifest.release_id,
        sequence=1,
        manifest_digest=manifest.digest,
        registry_digest=manifest.registry_digest,
        package_created_at=NOW,
        imported_at=NOW,
        admission_expires_at=NOW + timedelta(days=1),
        verified_key_id="fixture",
        sources=(document().evidence,),
    )
    assert b"processing_digests" not in canonical_bytes(binding)


def test_extended_normalizer_requires_new_reader_without_changing_old_bytes() -> None:
    manifest, registry, trust, key = release()
    original = canonical_bytes(manifest)
    old = document()
    updated = CloudStructuredDocument.model_validate(
        old.model_dump() | {"normalizer_version": "2.1.0"}
    )
    assert updated.evidence == old.evidence
    assert updated.recipe == old.recipe and updated.recipe_digest == old.recipe_digest
    assert updated.processing_digest != old.processing_digest
    assert structured_excerpts(updated)[0].text == structured_excerpts(old)[0].text
    assert structured_excerpts(updated)[0].unit_id != structured_excerpts(old)[0].unit_id
    values = manifest.model_dump() | {
        "documents": (updated,),
        "excerpt_digests": (excerpt_digest(updated),),
    }
    with pytest.raises(ValueError, match="reader"):
        KnowledgeStructuredReleaseManifest.model_validate(values)
    upgraded = KnowledgeStructuredReleaseManifest.model_validate(
        values | {"reader_version": "3.1.0"}
    )
    verified = verify_package(
        sign_release(upgraded, key_id="fixture", private_key=key),
        registry=registry,
        trust=trust,
        now=NOW,
    )
    assert verified.manifest == upgraded
    assert canonical_bytes(manifest) == original
    assert canonical_bytes(parse_knowledge_manifest(original)) == original


@pytest.mark.parametrize("version", ["2.0.1", "2.2.0", "9.0.0"])
def test_unknown_normalizer_does_not_become_an_installed_recipe(version: str) -> None:
    with pytest.raises(ValueError):
        CloudStructuredDocument.model_validate(
            document().model_dump() | {"normalizer_version": version}
        )
