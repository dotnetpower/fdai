"""Signed, authority-neutral manifests for future Rule activation cohorts."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest

_MAX_MANIFEST_VALIDITY = timedelta(hours=24)
_MAX_REVOCATION_AGE_SECONDS = 86_400
_SIGNATURE_DOMAIN = b"fdai.rule-activation-manifest.v1\0"


class RuleActivationManifestSource(StrEnum):
    """Non-direct source whose artifact identity requires a signature."""

    INSTALLATION = "installation"
    PULL_REQUEST = "pull_request"
    OFFLINE_PACKAGE = "offline_package"


class RuleRevisionIdentityRef(ContractBase):
    """One full immutable Rule revision selected by the manifest."""

    rule_id: Annotated[str, Field(min_length=1, max_length=256)]
    rule_version: Annotated[str, Field(min_length=1, max_length=64)]
    revision_digest: Digest

    @field_validator("rule_id", "rule_version", mode="before")
    @classmethod
    def _exact_identity(cls, value: object) -> object:
        return _exact_text(value, "Rule revision identity reference")


class RuleActivationManifest(ContractBase):
    """One signed inert activation intent; it cannot move an active pointer."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source: RuleActivationManifestSource
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_id: Annotated[str, Field(min_length=1, max_length=512)]
    target_generation_id: Annotated[str, Field(min_length=1, max_length=256)]
    target_generation_digest: Digest
    profile_id: Annotated[str, Field(min_length=1, max_length=128)]
    profile_version: Annotated[str, Field(min_length=1, max_length=64)]
    catalog_manifest_digest: Digest
    revision_registry_root: Digest
    members: Annotated[tuple[RuleRevisionIdentityRef, ...], Field(min_length=1, max_length=10_000)]
    deployment_scope_digest: Digest
    nonce: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    issued_at: datetime
    expires_at: datetime
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator(
        "release_id",
        "source_id",
        "target_generation_id",
        "profile_id",
        "profile_version",
        mode="before",
    )
    @classmethod
    def _exact_text_fields(cls, value: object) -> object:
        return _exact_text(value, "Rule activation manifest")

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule activation manifest time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_manifest(self) -> Self:
        if not self.issued_at < self.expires_at <= self.issued_at + _MAX_MANIFEST_VALIDITY:
            raise ValueError("Rule activation manifest validity MUST be positive and bounded")
        keys = tuple((member.rule_id, member.rule_version) for member in self.members)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("Rule activation manifest members MUST be unique and sorted")
        return self

    @property
    def manifest_digest(self) -> str:
        """Return the canonical manifest digest covered by the signature."""

        return canonical_digest(self.model_dump(mode="json"))


class RuleActivationTrustedKey(ContractBase):
    """One independently approved manifest-signing key."""

    key_id: Annotated[str, Field(min_length=1, max_length=128)]
    public_key: Annotated[str, Field(min_length=44, max_length=44, repr=False)]
    valid_from: datetime
    valid_until: datetime

    @field_validator("key_id", mode="before")
    @classmethod
    def _exact_key_id(cls, value: object) -> object:
        return _exact_text(value, "Rule activation key id")

    @field_validator("public_key")
    @classmethod
    def _raw_public_key(cls, value: str) -> str:
        _public_key(value)
        return value

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def _validity(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("Rule activation signing key validity MUST be positive")
        return self


class RuleActivationManifestTrust(ContractBase):
    """Current approval, rotation, and revocation state for manifest keys."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    purpose: Literal["fdai.rule-activation-manifest.v1"] = "fdai.rule-activation-manifest.v1"
    approved_by: Annotated[str, Field(min_length=1, max_length=256)]
    valid_from: datetime
    valid_until: datetime
    keys: Annotated[tuple[RuleActivationTrustedKey, ...], Field(min_length=1, max_length=128)]
    revoked_key_ids: Annotated[tuple[str, ...], Field(max_length=128)] = ()
    revocation_checked_at: datetime
    revocation_max_age_seconds: Annotated[int, Field(ge=1, le=_MAX_REVOCATION_AGE_SECONDS)] = 3600

    @field_validator("approved_by", mode="before")
    @classmethod
    def _exact_approved_by(cls, value: object) -> object:
        return _exact_text(value, "Rule activation trust approver")

    @field_validator("valid_from", "valid_until", "revocation_checked_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def _unambiguous_trust(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("Rule activation trust validity MUST be positive")
        key_ids = tuple(key.key_id for key in self.keys)
        public_keys = tuple(_public_key_bytes(key.public_key) for key in self.keys)
        if len(set(key_ids)) != len(key_ids) or len(set(public_keys)) != len(public_keys):
            raise ValueError("Rule activation signing keys MUST be unique")
        if len(set(self.revoked_key_ids)) != len(self.revoked_key_ids):
            raise ValueError("Rule activation revoked key ids MUST be unique")
        return self


class SignedRuleActivationManifest(ContractBase):
    """Signature envelope for one exact manifest."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: Annotated[str, Field(min_length=1, max_length=128)]
    manifest: RuleActivationManifest
    manifest_digest: Digest
    signature: Annotated[str, Field(min_length=88, max_length=88)]

    @field_validator("key_id", mode="before")
    @classmethod
    def _exact_key_id(cls, value: object) -> object:
        return _exact_text(value, "signed Rule activation key id")

    @model_validator(mode="after")
    def _digest_and_signature_shape(self) -> Self:
        if self.manifest_digest != self.manifest.manifest_digest:
            raise ValueError("signed Rule activation manifest digest mismatch")
        _signature_bytes(self.signature)
        return self


class RuleActivationManifestExpectation(ContractBase):
    """Trusted local interpretation of every signed manifest identity."""

    source: RuleActivationManifestSource
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_id: Annotated[str, Field(min_length=1, max_length=512)]
    target_generation_id: Annotated[str, Field(min_length=1, max_length=256)]
    target_generation_digest: Digest
    profile_id: Annotated[str, Field(min_length=1, max_length=128)]
    profile_version: Annotated[str, Field(min_length=1, max_length=64)]
    catalog_manifest_digest: Digest
    revision_registry_root: Digest
    members: Annotated[tuple[RuleRevisionIdentityRef, ...], Field(min_length=1, max_length=10_000)]
    deployment_scope_digest: Digest

    @field_validator(
        "release_id",
        "source_id",
        "target_generation_id",
        "profile_id",
        "profile_version",
        mode="before",
    )
    @classmethod
    def _exact_text_fields(cls, value: object) -> object:
        return _exact_text(value, "Rule activation manifest expectation")

    @model_validator(mode="after")
    def _canonical_members(self) -> Self:
        keys = tuple((member.rule_id, member.rule_version) for member in self.members)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("Rule activation manifest expected members MUST be unique and sorted")
        return self


def sign_rule_activation_manifest(
    manifest: RuleActivationManifest,
    *,
    key_id: str,
    private_key: Ed25519PrivateKey,
) -> SignedRuleActivationManifest:
    """Sign a manifest for packaging; the result grants no activation authority."""

    signature = private_key.sign(_signing_bytes(manifest))
    return SignedRuleActivationManifest(
        key_id=key_id,
        manifest=manifest,
        manifest_digest=manifest.manifest_digest,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def verify_rule_activation_manifest(
    envelope: SignedRuleActivationManifest,
    *,
    trust: RuleActivationManifestTrust,
    now: datetime,
    expected: RuleActivationManifestExpectation,
    consumed_nonces: Collection[str] = (),
) -> RuleActivationManifest:
    """Verify signature, trust, freshness, scope, registry root, and replay state."""

    current = _aware(now)
    if not trust.valid_from <= current < trust.valid_until:
        raise ValueError("Rule activation manifest trust is not currently valid")
    if trust.revocation_checked_at > current:
        raise ValueError("Rule activation revocation check MUST NOT be future-dated")
    if current >= trust.revocation_checked_at + timedelta(seconds=trust.revocation_max_age_seconds):
        raise ValueError("Rule activation revocation evidence is stale")
    key = next((item for item in trust.keys if item.key_id == envelope.key_id), None)
    if key is None or envelope.key_id in trust.revoked_key_ids:
        raise ValueError("Rule activation signing key is not approved or is revoked")
    manifest = envelope.manifest
    if not key.valid_from <= manifest.issued_at <= current < key.valid_until:
        raise ValueError("Rule activation signing key or manifest time is invalid")
    if not manifest.issued_at <= current < manifest.expires_at:
        raise ValueError("Rule activation manifest is not currently valid")
    actual_identity = RuleActivationManifestExpectation(
        source=manifest.source,
        release_id=manifest.release_id,
        source_id=manifest.source_id,
        target_generation_id=manifest.target_generation_id,
        target_generation_digest=manifest.target_generation_digest,
        profile_id=manifest.profile_id,
        profile_version=manifest.profile_version,
        catalog_manifest_digest=manifest.catalog_manifest_digest,
        revision_registry_root=manifest.revision_registry_root,
        members=manifest.members,
        deployment_scope_digest=manifest.deployment_scope_digest,
    )
    if actual_identity != expected:
        raise ValueError("Rule activation manifest identity mismatch")
    if manifest.nonce in consumed_nonces:
        raise ValueError("Rule activation manifest nonce was already consumed")
    try:
        _public_key(key.public_key).verify(
            _signature_bytes(envelope.signature),
            _signing_bytes(manifest),
        )
    except InvalidSignature as exc:
        raise ValueError("Rule activation manifest signature is invalid") from exc
    return manifest


def rule_revision_registry_root(members: Collection[RuleRevisionIdentityRef]) -> str:
    """Return the canonical root for one complete retained revision set."""

    ordered = tuple(sorted(members, key=lambda member: (member.rule_id, member.rule_version)))
    if not ordered or len({(member.rule_id, member.rule_version) for member in ordered}) != len(
        ordered
    ):
        raise ValueError("Rule revision registry root requires unique members")
    return canonical_digest([member.model_dump(mode="json") for member in ordered])


def _signing_bytes(manifest: RuleActivationManifest) -> bytes:
    return _SIGNATURE_DOMAIN + manifest.manifest_digest.encode("ascii")


def _public_key(value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(_public_key_bytes(value))


def _public_key_bytes(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Rule activation public key MUST be canonical base64") from exc
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("Rule activation public key MUST encode 32 raw bytes")
    return raw


def _signature_bytes(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Rule activation signature MUST be canonical base64") from exc
    if len(raw) != 64 or base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("Rule activation signature MUST encode 64 raw bytes")
    return raw


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Rule activation verification time MUST include a timezone")
    return value.astimezone(UTC)


def _exact_text(value: object, label: str) -> object:
    if isinstance(value, str) and value != value.strip():
        raise ValueError(f"{label} MUST be exact")
    return value


__all__ = [
    "RuleActivationManifest",
    "RuleActivationManifestSource",
    "RuleActivationManifestExpectation",
    "RuleActivationManifestTrust",
    "RuleActivationTrustedKey",
    "RuleRevisionIdentityRef",
    "SignedRuleActivationManifest",
    "rule_revision_registry_root",
    "sign_rule_activation_manifest",
    "verify_rule_activation_manifest",
]
