"""Purpose-specific native workload creation evidence, not namespace ownership."""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest

type Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
type PathId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
type DnsName = Annotated[str, StringConstraints(pattern=r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")]
type ProductId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,62}$")]


class NativeScope(BaseModel):
    """Exact private creation scope, independently supplied by the customer."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    installation_id: PathId
    entity_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")]
    product: ProductId
    namespace: DnsName
    components: Annotated[tuple[DnsName, ...], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def validate_components(self) -> Self:
        if tuple(sorted(set(self.components))) != self.components:
            raise ValueError("native components must be unique and sorted")
        if self.anchor_name in self.components:
            raise ValueError("a workload component conflicts with the native anchor")
        return self

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))

    @property
    def anchor_name(self) -> str:
        identity = canonical_bytes(
            {"installation_id": self.installation_id, "entity_id": self.entity_id}
        )
        return "lifecycle-scope-" + hashlib.sha256(identity).hexdigest()[:20]

    @property
    def resources(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (kind, component) for component in self.components for kind in ("Deployment", "Service")
        )


class NativeApproval(BaseModel):
    """Local human approval. A signed package or Hub request cannot supply this input."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-approval.v1"]
    scope: NativeScope
    profile: Literal["full-authority-development"]
    approved_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9@._ -]{0,127}$")]
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.approved_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("native approval requires timezone-aware timestamps")
        if not timedelta(0) < self.expires_at - self.approved_at <= timedelta(hours=4):
            raise ValueError("native approval duration must be positive and at most four hours")
        return self

    def require_current(self, now: datetime) -> None:
        if now.utcoffset() is None or not self.approved_at <= now < self.expires_at:
            raise ValueError("native approval is not currently valid")

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))


class NativeScopeClaim(BaseModel):
    """Public digests of actual local creation; no namespace, UID or credential leaves."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-scope.v1"]
    installation_id: PathId
    entity_id: PathId
    product: ProductId
    scope_digest: Digest
    approval_digest: Digest
    creation_receipt_digest: Digest

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))


class SignedNativeScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    claim: NativeScopeClaim
    signature: Annotated[str, StringConstraints(min_length=88, max_length=88)]

    @model_validator(mode="after")
    def validate_signature(self) -> Self:
        try:
            decoded = base64.b64decode(self.signature, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("native scope signature encoding is invalid") from error
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != self.signature:
            raise ValueError("native scope signature must be canonical Ed25519 bytes")
        return self

    def verify(self, public_key: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                base64.b64decode(self.signature, validate=True), self.claim.payload
            )
        except (ValueError, InvalidSignature):
            return False
        return True


def sign_native_scope(claim: NativeScopeClaim, key: Ed25519PrivateKey) -> SignedNativeScope:
    return SignedNativeScope(
        claim=claim, signature=base64.b64encode(key.sign(claim.payload)).decode("ascii")
    )


class NativeOwnershipAcceptance(BaseModel):
    """Separate customer-operator acceptance, serialized with installation planning."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: UUID
    expected_settings_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    proof: SignedNativeScope
    reason: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    confirmation: Annotated[str, StringConstraints(max_length=512)]

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if not self.reason.strip() or any(ord(character) < 32 for character in self.reason):
            raise ValueError("native acceptance requires a nonblank single-line reason")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))

    @property
    def required_confirmation(self) -> str:
        claim = self.proof.claim
        return (
            f"accept native scope {claim.installation_id} {claim.entity_id} "
            f"{claim.digest} {self.expected_settings_digest}"
        )
