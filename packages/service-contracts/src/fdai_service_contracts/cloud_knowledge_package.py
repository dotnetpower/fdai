"""Bounded, data-only knowledge packages with independently supplied Ed25519 trust.

The signature authenticates producer assertions, not source truth or authority.
This codec performs no I/O, key loading/generation, scanning, indexing, or activation.
Importers retain durable replay fencing and the existing document-agent gates.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Final, Literal, NoReturn, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, StrictInt, field_validator, model_validator

from fdai_service_contracts.cloud_knowledge import (
    DAY,
    Digest,
    Identifier,
    KnowledgeContract,
    SourceRegistryRevision,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_release import (
    KnowledgeReleaseBinding,
    KnowledgeReleaseManifest,
)

MAX_PACKAGE_BYTES: Final = 16 * 1024 * 1024
PACKAGE_PURPOSE: Final = "fdai.cloud-knowledge.release.v1"
_SIGNATURE_DOMAIN: Final = PACKAGE_PURPOSE.encode("ascii") + b"\x00"

__all__ = [
    "MAX_PACKAGE_BYTES",
    "PACKAGE_PURPOSE",
    "KnowledgePackageError",
    "KnowledgeTrustPolicy",
    "KnowledgeTrustedKey",
    "VerifiedKnowledgePackage",
    "assemble_signed_release",
    "sign_release",
    "verify_package",
]


class KnowledgePackageError(ValueError):
    """A package or its independent verification inputs failed closed, without content details."""


def _public_key_bytes(value: str) -> bytes:
    """Accept only a raw 32-byte public key as hex or canonical padded base64, never PEM."""
    if re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return bytes.fromhex(value)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise KnowledgePackageError("public key MUST be raw hex or canonical base64") from None
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != value:
        raise KnowledgePackageError("public key MUST encode exactly 32 raw bytes")
    return decoded


class KnowledgeTrustedKey(KnowledgeContract):
    """An independently approved knowledge-signing identity with a bounded validity window."""

    key_id: Identifier
    public_key: Annotated[str, Field(min_length=44, max_length=64, repr=False)]
    valid_from: datetime
    valid_until: datetime

    @field_validator("key_id")
    @classmethod
    def not_a_collector_identity(cls, value: str) -> str:
        if value == "connected-collector":
            raise ValueError("knowledge signer cannot use the internal collector identity")
        return value

    @field_validator("public_key")
    @classmethod
    def raw_public_key(cls, value: str) -> str:
        """Reject key containers, locators, malformed encodings, and non-Ed25519 lengths."""
        _public_key_bytes(value)
        return value

    @model_validator(mode="after")
    def validity_window(self) -> Self:
        """Require a nonempty delegation window; the verifier applies its trusted clock."""
        if self.valid_until <= self.valid_from:
            raise ValueError("knowledge key validity MUST end after it starts")
        return self


class KnowledgeTrustPolicy(KnowledgeContract):
    """Current independent approval and revocation evidence, never accepted from a package.

    Revocation evidence expires at its check time plus the approved maximum age.
    This is a supplied trust decision, not a trust-bootstrap or signature-rotation protocol.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    purpose: Literal["fdai.cloud-knowledge.release.v1"] = PACKAGE_PURPOSE
    approved_by: Identifier
    valid_from: datetime
    valid_until: datetime
    keys: Annotated[tuple[KnowledgeTrustedKey, ...], Field(min_length=1, max_length=128)]
    revocation_checked_at: datetime
    revocation_max_age_seconds: Annotated[StrictInt, Field(ge=1, le=365 * DAY)] = DAY
    revoked_key_ids: Annotated[tuple[Identifier, ...], Field(max_length=1024)] = ()

    @model_validator(mode="after")
    def unambiguous_trust(self) -> Self:
        """Prevent ambiguous key selectors and aliases that could relabel an unsigned key id."""
        if self.valid_until <= self.valid_from:
            raise ValueError("knowledge trust validity MUST end after it starts")
        ids = [key.key_id for key in self.keys]
        material = [_public_key_bytes(key.public_key) for key in self.keys]
        if len(set(ids)) != len(ids) or len(set(material)) != len(material):
            raise ValueError("knowledge key identities and public keys MUST be unique")
        if len(set(self.revoked_key_ids)) != len(self.revoked_key_ids):
            raise ValueError("revoked knowledge key identities MUST be unique")
        return self


class _PackageEnvelope(KnowledgeContract):
    """Closed JSON envelope; signature is lowercase hex over domain plus canonical manifest."""

    schema_version: Literal["fdai.cloud-knowledge-package.v1"] = "fdai.cloud-knowledge-package.v1"
    purpose: Literal["fdai.cloud-knowledge.release.v1"] = PACKAGE_PURPOSE
    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: Identifier
    manifest_digest: Digest
    manifest: KnowledgeReleaseManifest
    signature: Annotated[str, Field(min_length=128, max_length=128, pattern=r"^[0-9a-f]{128}$")]


@dataclass(frozen=True, slots=True)
class VerifiedKnowledgePackage:
    """Verified advisory input for the existing document pipeline, not an admission approval.

    ``content`` is exact canonical manifest JSON, not the transport envelope, and
    its SHA-256 equals ``binding.manifest_digest``. Source dates are unchanged.
    No document body or provenance is included in the default representation.
    """

    manifest: KnowledgeReleaseManifest = field(repr=False)
    content: bytes = field(repr=False)
    binding: KnowledgeReleaseBinding = field(repr=False)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise KnowledgePackageError("package JSON MUST NOT contain duplicate keys")
        result[key] = value
    return result


def _reject_number(value: str) -> NoReturn:
    # This wire contract has no float fields, including numeric timestamp aliases.
    raise KnowledgePackageError("package JSON numbers MUST be finite integers")


def _decode_package(content: bytes) -> _PackageEnvelope:
    try:
        raw: object = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        envelope = _PackageEnvelope.model_validate(raw)
        if canonical_bytes(envelope) != content:
            raise KnowledgePackageError("package and manifest MUST use exact canonical JSON")
        return envelope
    except KnowledgePackageError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError):
        # Pydantic/JSON errors can contain source text; never propagate those details.
        raise KnowledgePackageError(
            "package MUST contain valid closed UTF-8 JSON contracts"
        ) from None


def assemble_signed_release(
    manifest: KnowledgeReleaseManifest, *, key_id: str, signature: bytes
) -> bytes:
    """Package a detached external signature; callers still verify independent trust.

    This allows offline packaging without giving FDAI a signing key. The signature
    is over the purpose-domain-separated canonical manifest documented by sign_release.
    """
    if len(signature) != 64:
        raise KnowledgePackageError("knowledge signature MUST contain 64 bytes")
    encoded = canonical_bytes(
        _PackageEnvelope(
            key_id=key_id,
            manifest_digest=manifest.digest,
            manifest=manifest,
            signature=signature.hex(),
        )
    )
    if len(encoded) > MAX_PACKAGE_BYTES:
        raise KnowledgePackageError("knowledge package exceeds the byte limit")
    return encoded


def sign_release(
    manifest: KnowledgeReleaseManifest, *, key_id: str, private_key: Ed25519PrivateKey
) -> bytes:
    """Encode and sign a bounded release using an injected, externally reviewed signing key.

    Signs ``PACKAGE_PURPOSE.encode('ascii') + b'\\x00' + canonical_bytes(manifest)``.
    The separate key id selects independent verifier trust; no key is loaded, generated,
    exported, or bundled here. This primitive does not establish rights, time, or approval.
    Invalid contracts and packages above the hard byte ceiling raise ``KnowledgePackageError``.
    """
    if not isinstance(private_key, Ed25519PrivateKey):
        raise KnowledgePackageError("signer MUST supply an Ed25519 private key object")
    try:
        checked = KnowledgeReleaseManifest.model_validate(manifest.model_dump(warnings="error"))
        stored = canonical_bytes(checked)
        if len(stored) > MAX_PACKAGE_BYTES:
            raise KnowledgePackageError("knowledge package exceeds the byte limit")
        envelope = _PackageEnvelope(
            key_id=key_id,
            manifest_digest=content_digest(stored),
            manifest=checked,
            signature=private_key.sign(_SIGNATURE_DOMAIN + stored).hex(),
        )
        encoded = canonical_bytes(envelope)
    except KnowledgePackageError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise KnowledgePackageError(
            "signer MUST supply valid knowledge release contracts"
        ) from None
    if len(encoded) > MAX_PACKAGE_BYTES:
        raise KnowledgePackageError("knowledge package exceeds the byte limit")
    return encoded


def _current_key(
    envelope: _PackageEnvelope, trust: KnowledgeTrustPolicy, now: datetime
) -> tuple[KnowledgeTrustedKey, datetime]:
    """Use strict time boundaries: no future-clock grace and no stale revocation fallback."""
    if not trust.valid_from <= now < trust.valid_until:
        raise KnowledgePackageError("knowledge trust policy is not currently valid")
    if trust.revocation_checked_at > now:
        raise KnowledgePackageError("revocation evidence MUST NOT be future-dated")
    try:
        revocation_expires = trust.revocation_checked_at + timedelta(
            seconds=trust.revocation_max_age_seconds
        )
    except OverflowError:
        raise KnowledgePackageError(
            "revocation validity exceeds the supported clock range"
        ) from None
    if now >= revocation_expires:
        raise KnowledgePackageError("knowledge revocation evidence is stale")
    key = next((item for item in trust.keys if item.key_id == envelope.key_id), None)
    if key is None or envelope.key_id in trust.revoked_key_ids:
        raise KnowledgePackageError("knowledge signing key is not approved or is revoked")
    if not key.valid_from <= envelope.manifest.package_created_at <= now < key.valid_until:
        raise KnowledgePackageError("knowledge signing key or package time is not valid")
    return key, revocation_expires


def _registered_collection(
    manifest: KnowledgeReleaseManifest, registry: SourceRegistryRevision
) -> None:
    """A complete selected collection cannot shrink after failed collection or broaden origin."""
    if manifest.registry_digest != registry.digest:
        raise KnowledgePackageError("release MUST bind the exact approved source registry digest")
    selected = {
        source.source_id: source
        for source in registry.sources
        if source.collection_id == manifest.collection_id
    }
    if not selected:
        raise KnowledgePackageError("release collection MUST exist in the approved source registry")
    represented = {doc.evidence.source_id for doc in manifest.documents}
    represented.update(manifest.withdrawn_source_ids)
    if represented != set(selected):
        raise KnowledgePackageError("release MUST cover exactly the complete registered collection")
    for document in manifest.documents:
        evidence = document.evidence
        source = selected[evidence.source_id]
        if (
            evidence.source_url != source.url
            or evidence.applicability != source.applicability
            or evidence.policy != source.policy
            or evidence.license_ref != source.license_ref
            or document.title != source.title
        ):
            raise KnowledgePackageError(
                "document provenance MUST match its registered source exactly"
            )
        if not source.storage_allowed or not source.internal_transfer_allowed:
            raise KnowledgePackageError(
                "full-text packages require storage and internal transfer rights"
            )
        if any(
            len(text.encode("utf-8")) > source.max_bytes
            for text in (document.original_text, document.text)
        ):
            raise KnowledgePackageError("document text exceeds its registered source byte limit")
        if (
            evidence.source_updated_at is not None
            and evidence.source_updated_at > evidence.collected_at
        ):
            raise KnowledgePackageError("source modification time MUST NOT follow body collection")


def verify_package(
    content: bytes,
    *,
    registry: SourceRegistryRevision,
    trust: KnowledgeTrustPolicy,
    now: datetime,
    max_bytes: int = MAX_PACKAGE_BYTES,
    minimum_sequence: int = 0,
) -> VerifiedKnowledgePackage:
    """Verify a complete advisory package offline against independently approved inputs.

    Byte limits may only narrow the hard ceiling. All timestamps use the supplied aware
    clock without positive-skew grace. Expiry includes registry, trust, key, manifest,
    and revocation validity, but NOT actual-source age: freshness remains separate.
    ``minimum_sequence`` is a strict preflight floor only; the importer must atomically
    enforce its durable collection high-water mark and audit through the document pipeline.
    Invalid input raises content-free ``KnowledgePackageError`` without persistent effects.
    """
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_PACKAGE_BYTES:
        raise KnowledgePackageError(
            "package byte limit MUST be positive and within the hard ceiling"
        )
    if type(minimum_sequence) is not int or minimum_sequence < 0:
        raise KnowledgePackageError("minimum release sequence MUST be a nonnegative integer")
    if not isinstance(content, bytes) or not 0 < len(content) <= max_bytes:
        raise KnowledgePackageError("knowledge package is empty or exceeds the byte limit")
    if now.utcoffset() is None:
        raise KnowledgePackageError("package verification clock MUST be timezone-aware")
    envelope = _decode_package(content)
    try:
        # Revalidate snapshots, including callers' unchecked model_copy updates.
        registry = SourceRegistryRevision.model_validate(registry.model_dump(warnings="error"))
        trust = KnowledgeTrustPolicy.model_validate(trust.model_dump(warnings="error"))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise KnowledgePackageError(
            "registry and trust MUST be independently valid contracts"
        ) from None
    if registry.valid_until <= now:
        raise KnowledgePackageError("source registry approval has expired")
    key, revocation_expires = _current_key(envelope, trust, now)
    manifest = envelope.manifest
    stored = canonical_bytes(manifest)
    if content_digest(stored) != envelope.manifest_digest:
        raise KnowledgePackageError("package manifest digest does not match its exact content")
    try:
        Ed25519PublicKey.from_public_bytes(_public_key_bytes(key.public_key)).verify(
            bytes.fromhex(envelope.signature), _SIGNATURE_DOMAIN + stored
        )
    except InvalidSignature:
        raise KnowledgePackageError("knowledge package signature verification failed") from None
    if manifest.sequence <= minimum_sequence:
        raise KnowledgePackageError("release sequence MUST exceed the supplied high-water mark")
    expires = min(
        registry.valid_until,
        trust.valid_until,
        key.valid_until,
        revocation_expires,
        manifest.expires_at,
    )
    if now >= expires:
        raise KnowledgePackageError("knowledge package admission has expired")
    _registered_collection(manifest, registry)
    binding = KnowledgeReleaseBinding(
        release_id=manifest.release_id,
        sequence=manifest.sequence,
        manifest_digest=content_digest(stored),
        registry_digest=manifest.registry_digest,
        package_created_at=manifest.package_created_at,
        imported_at=now,
        admission_expires_at=expires,
        verified_key_id=key.key_id,
        sources=tuple(document.evidence for document in manifest.documents),
        withdrawn_source_ids=manifest.withdrawn_source_ids,
    )
    return VerifiedKnowledgePackage(manifest=manifest, content=stored, binding=binding)
