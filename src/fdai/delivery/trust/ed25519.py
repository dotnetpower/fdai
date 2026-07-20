"""Domain-separated Ed25519 verification for extensions and skills."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from fdai.core.capability_catalog.extensions import ExtensionManifest
from fdai.core.skills.bundle_manifest import RuntimeSkillBundle
from fdai.core.skills.catalog import RuntimeSkill
from fdai.core.supply_chain import TrustedArtifactKind, TrustedArtifactRecord


@dataclass(frozen=True, slots=True)
class Ed25519ExtensionTrustVerifier:
    """Verify one detached extension signature against a publisher registry."""

    trusted_publishers: Mapping[str, bytes]
    signature: bytes

    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        if hashlib.sha256(archive).hexdigest() != manifest.archive_sha256:
            return False
        return _verify(
            self.trusted_publishers.get(manifest.source),
            self.signature,
            extension_signature_payload(manifest),
        )


@dataclass(frozen=True, slots=True)
class Ed25519SkillTrustVerifier:
    """Verify one detached skill signature against a publisher registry."""

    trusted_publishers: Mapping[str, bytes]
    signature: bytes

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return _verify(
            self.trusted_publishers.get(skill.manifest.source),
            self.signature,
            skill_signature_payload(skill, raw_markdown),
        )


@dataclass(frozen=True, slots=True, init=False)
class Ed25519SkillTrustVerifierFactory:
    """Create signature-bound skill verifiers from an immutable publisher snapshot."""

    _trusted_publishers: Mapping[str, bytes]

    def __init__(self, trusted_publishers: Mapping[str, bytes]) -> None:
        snapshot = MappingProxyType(
            {source: bytes(public_key) for source, public_key in trusted_publishers.items()}
        )
        object.__setattr__(self, "_trusted_publishers", snapshot)

    def __call__(self, record: TrustedArtifactRecord, /) -> Ed25519SkillTrustVerifier:
        if record.kind is not TrustedArtifactKind.SKILL:
            raise ValueError("Ed25519 skill verifier factory requires a skill record")
        return Ed25519SkillTrustVerifier(
            trusted_publishers=self._trusted_publishers,
            signature=record.signature,
        )


@dataclass(frozen=True, slots=True, init=False)
class Ed25519SkillCatalogVerifier:
    """Recheck loaded skills against immutable record-bound signatures."""

    _records: Mapping[str, TrustedArtifactRecord]
    _verifiers: Mapping[str, Ed25519SkillTrustVerifier]

    def __init__(
        self,
        records: tuple[TrustedArtifactRecord, ...],
        trusted_publishers: Mapping[str, bytes],
    ) -> None:
        if any(record.kind is not TrustedArtifactKind.SKILL for record in records):
            raise ValueError("Ed25519 skill catalog verifier requires only skill records")
        by_id = {record.artifact_id: record for record in records}
        if len(by_id) != len(records):
            raise ValueError("Ed25519 skill catalog verifier requires unique skill records")
        factory = Ed25519SkillTrustVerifierFactory(trusted_publishers)
        object.__setattr__(self, "_records", MappingProxyType(by_id))
        object.__setattr__(
            self,
            "_verifiers",
            MappingProxyType(
                {artifact_id: factory(record) for artifact_id, record in by_id.items()}
            ),
        )

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        record = self._records.get(skill.manifest.name)
        verifier = self._verifiers.get(skill.manifest.name)
        if record is None or verifier is None:
            return False
        if record.version != skill.manifest.version or record.source != skill.manifest.source:
            return False
        return verifier.verify(skill, raw_markdown)


@dataclass(frozen=True, slots=True)
class Ed25519SkillBundleTrustVerifier:
    """Verify a governed bundle in its own non-replayable signature domain."""

    trusted_publishers: Mapping[str, bytes]
    signature: bytes

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        if raw_manifest != bundle.raw_manifest:
            return False
        return _verify(
            self.trusted_publishers.get(bundle.manifest.source),
            self.signature,
            skill_bundle_signature_payload(bundle),
        )


@dataclass(frozen=True, slots=True, init=False)
class Ed25519SkillBundleVerifierFactory:
    """Create record-bound governed bundle verifiers from trusted publishers."""

    _trusted_publishers: Mapping[str, bytes]

    def __init__(self, trusted_publishers: Mapping[str, bytes]) -> None:
        object.__setattr__(
            self,
            "_trusted_publishers",
            MappingProxyType(
                {source: bytes(public_key) for source, public_key in trusted_publishers.items()}
            ),
        )

    def __call__(self, record: TrustedArtifactRecord, /) -> Ed25519SkillBundleTrustVerifier:
        if record.kind is not TrustedArtifactKind.SKILL_BUNDLE:
            raise ValueError("Ed25519 bundle verifier factory requires a bundle record")
        return Ed25519SkillBundleTrustVerifier(
            trusted_publishers=self._trusted_publishers,
            signature=record.signature,
        )


@dataclass(frozen=True, slots=True, init=False)
class Ed25519SkillBundleCatalogVerifier:
    """Recheck loaded governed bundles against record-bound signatures."""

    _records: Mapping[str, TrustedArtifactRecord]
    _verifiers: Mapping[str, Ed25519SkillBundleTrustVerifier]

    def __init__(
        self,
        records: tuple[TrustedArtifactRecord, ...],
        trusted_publishers: Mapping[str, bytes],
    ) -> None:
        if any(record.kind is not TrustedArtifactKind.SKILL_BUNDLE for record in records):
            raise ValueError("Ed25519 bundle catalog verifier requires only bundle records")
        by_id = {record.artifact_id: record for record in records}
        if len(by_id) != len(records):
            raise ValueError("Ed25519 bundle catalog verifier requires unique bundle records")
        factory = Ed25519SkillBundleVerifierFactory(trusted_publishers)
        object.__setattr__(self, "_records", MappingProxyType(by_id))
        object.__setattr__(
            self,
            "_verifiers",
            MappingProxyType(
                {artifact_id: factory(record) for artifact_id, record in by_id.items()}
            ),
        )

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        record = self._records.get(bundle.manifest.name)
        verifier = self._verifiers.get(bundle.manifest.name)
        if record is None or verifier is None:
            return False
        if record.version != bundle.manifest.version or record.source != bundle.manifest.source:
            return False
        return verifier.verify(bundle, raw_manifest)


@dataclass(frozen=True, slots=True)
class Ed25519ModelEndpointRegistrationVerifier:
    """Verify signed self-hosted model endpoint registration bytes."""

    trusted_publishers: Mapping[str, bytes]

    def verify(self, *, source: str, document: bytes, signature: bytes) -> bool:
        return _verify(
            self.trusted_publishers.get(source),
            signature,
            model_endpoint_registration_signature_payload(source, document),
        )


def extension_signature_payload(manifest: ExtensionManifest) -> bytes:
    """Canonical domain-separated extension signature payload."""
    return _payload(
        "fdai.extension-signature.v1",
        manifest.source,
        manifest.extension_id,
        manifest.version,
        manifest.archive_sha256,
    )


def skill_signature_payload(skill: RuntimeSkill, raw_markdown: bytes) -> bytes:
    """Canonical domain-separated skill signature payload."""
    return _payload(
        "fdai.skill-signature.v1",
        skill.manifest.source,
        skill.manifest.name,
        skill.manifest.version,
        hashlib.sha256(raw_markdown).hexdigest(),
    )


def skill_bundle_signature_payload(bundle: RuntimeSkillBundle) -> bytes:
    """Canonical domain-separated payload for governed bundle manifests."""
    return _payload(
        "fdai.skill-bundle-signature.v1",
        bundle.manifest.source,
        bundle.manifest.name,
        bundle.manifest.version,
        bundle.manifest.digest,
    )


def model_endpoint_registration_signature_payload(source: str, document: bytes) -> bytes:
    """Canonical domain-separated payload for a self-hosted endpoint record."""
    return _payload(
        "fdai.model-endpoint-registration.v1",
        source,
        hashlib.sha256(document).hexdigest(),
    )


def _payload(*parts: str) -> bytes:
    if any(not part or "\0" in part for part in parts):
        raise ValueError("signature payload fields MUST be non-empty and NUL-free")
    return "\0".join(parts).encode("utf-8")


def _verify(public_key_pem: bytes | None, signature: bytes, payload: bytes) -> bool:
    if public_key_pem is None or len(signature) != 64:
        return False
    try:
        key = load_pem_public_key(public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(signature, payload)
    except (InvalidSignature, TypeError, ValueError):
        return False
    return True


__all__ = [
    "Ed25519ExtensionTrustVerifier",
    "Ed25519ModelEndpointRegistrationVerifier",
    "Ed25519SkillCatalogVerifier",
    "Ed25519SkillBundleTrustVerifier",
    "Ed25519SkillBundleCatalogVerifier",
    "Ed25519SkillBundleVerifierFactory",
    "Ed25519SkillTrustVerifier",
    "Ed25519SkillTrustVerifierFactory",
    "extension_signature_payload",
    "model_endpoint_registration_signature_payload",
    "skill_bundle_signature_payload",
    "skill_signature_payload",
]
