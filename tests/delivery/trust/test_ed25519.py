"""Concrete extension and skill Ed25519 trust verification tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.core.capability_catalog.extensions import ExtensionManifest
from fdai.core.skills.bundle_manifest import (
    encode_skill_bundle_manifest,
    parse_skill_bundle_manifest,
)
from fdai.core.skills.catalog import RuntimeSkill, parse_skill_markdown, skill_body_digest
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.delivery.trust.ed25519 import (
    Ed25519ExtensionTrustVerifier,
    Ed25519SkillBundleTrustVerifier,
    Ed25519SkillCatalogVerifier,
    Ed25519SkillTrustVerifier,
    Ed25519SkillTrustVerifierFactory,
    extension_signature_payload,
    skill_bundle_signature_payload,
    skill_signature_payload,
)


def _keys() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


def _extension(archive: bytes, *, source: str = "publisher.example") -> ExtensionManifest:
    return ExtensionManifest(
        extension_id="example.extension",
        version="1.2.3",
        source=source,
        archive_sha256=hashlib.sha256(archive).hexdigest(),
        min_host_version="1.0.0",
    )


def _skill(*, source: str = "publisher.example") -> tuple[RuntimeSkill, bytes]:
    body = "Use deterministic tools only."
    raw = (
        "---\n"
        "name: example.skill\n"
        "version: 1.2.3\n"
        "description: Example\n"
        f"source: {source}\n"
        f"body_sha256: {skill_body_digest(body)}\n"
        "required_tools: []\n"
        "allowed_agents: []\n"
        "---\n"
        f"{body}\n"
    ).encode()
    return parse_skill_markdown(raw), raw


def test_extension_signature_verifies_and_rejects_replay() -> None:
    private, public = _keys()
    archive = b"extension archive"
    manifest = _extension(archive)
    signature = private.sign(extension_signature_payload(manifest))
    verifier = Ed25519ExtensionTrustVerifier(
        trusted_publishers={manifest.source: public},
        signature=signature,
    )

    assert verifier.verify(manifest, archive) is True
    assert verifier.verify(manifest, b"changed") is False
    assert verifier.verify(_extension(archive, source="other.publisher"), archive) is False


def test_skill_signature_verifies_full_markdown_and_rejects_cross_kind() -> None:
    private, public = _keys()
    skill, raw = _skill()
    signature = private.sign(skill_signature_payload(skill, raw))
    verifier = Ed25519SkillTrustVerifier(
        trusted_publishers={skill.manifest.source: public},
        signature=signature,
    )

    assert verifier.verify(skill, raw) is True
    assert verifier.verify(skill, raw + b" ") is False
    extension = _extension(b"archive")
    assert signature != private.sign(extension_signature_payload(extension))


def test_non_ed25519_key_and_invalid_signature_fail_closed() -> None:
    _private, public = _keys()
    skill, raw = _skill()
    verifier = Ed25519SkillTrustVerifier(
        trusted_publishers={skill.manifest.source: public},
        signature=b"short",
    )

    assert verifier.verify(skill, raw) is False


def test_skill_verifier_factory_binds_record_signature_and_snapshots_publishers() -> None:
    private, public = _keys()
    skill, raw = _skill()
    signature = private.sign(skill_signature_payload(skill, raw))
    publishers = {skill.manifest.source: public}
    factory = Ed25519SkillTrustVerifierFactory(publishers)
    publishers.clear()
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    record = TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id=skill.manifest.name,
        version=skill.manifest.version,
        source=skill.manifest.source,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=signature,
        state=TrustedArtifactState.DISABLED,
        revision=1,
        created_at=now,
        updated_at=now,
    )

    assert factory(record).verify(skill, raw) is True


def test_skill_catalog_verifier_rechecks_record_identity_and_signature() -> None:
    private, public = _keys()
    skill, raw = _skill()
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    record = TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id=skill.manifest.name,
        version=skill.manifest.version,
        source=skill.manifest.source,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=private.sign(skill_signature_payload(skill, raw)),
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    verifier = Ed25519SkillCatalogVerifier((record,), {skill.manifest.source: public})
    other_skill, other_raw = _skill(source="other.publisher")

    assert verifier.verify(skill, raw) is True
    assert verifier.verify(skill, raw + b" ") is False
    assert verifier.verify(other_skill, other_raw) is False


def test_skill_catalog_verifier_rejects_duplicate_and_non_skill_records() -> None:
    private, public = _keys()
    skill, raw = _skill()
    now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    record = TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id=skill.manifest.name,
        version=skill.manifest.version,
        source=skill.manifest.source,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=private.sign(skill_signature_payload(skill, raw)),
        state=TrustedArtifactState.DISABLED,
        revision=1,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(ValueError, match="unique"):
        Ed25519SkillCatalogVerifier((record, record), {skill.manifest.source: public})
    with pytest.raises(ValueError, match="only skill"):
        Ed25519SkillCatalogVerifier(
            (replace(record, kind=TrustedArtifactKind.EXTENSION),),
            {skill.manifest.source: public},
        )


def test_skill_bundle_signature_is_domain_separated_and_manifest_bound() -> None:
    private, public = _keys()
    raw = encode_skill_bundle_manifest(
        {
            "name": "incident-evidence-pack",
            "version": "1.0.0",
            "description": "Reviewed incident evidence procedures.",
            "source": "publisher.example",
            "members": [{"name": "example.skill", "version": "==1.2.3"}],
            "allowed_agents": ["Bragi"],
            "required_tools": [],
            "instruction": None,
        }
    )
    bundle = parse_skill_bundle_manifest(raw)
    signature = private.sign(skill_bundle_signature_payload(bundle))
    verifier = Ed25519SkillBundleTrustVerifier(
        trusted_publishers={bundle.manifest.source: public},
        signature=signature,
    )
    skill, skill_raw = _skill()

    assert verifier.verify(bundle, raw) is True
    assert verifier.verify(bundle, raw + b" ") is False
    assert signature != private.sign(skill_signature_payload(skill, skill_raw))
