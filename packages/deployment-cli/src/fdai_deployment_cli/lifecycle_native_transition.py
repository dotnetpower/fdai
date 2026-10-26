"""Signed authorization for one installed legacy-to-native workload scope transition."""

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
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native import Digest, PathId

type HexDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type InstallationKeyId = Annotated[str, StringConstraints(pattern=r"^installation-[0-9a-f]{16}$")]
type HubKeyId = Annotated[str, StringConstraints(pattern=r"^hub-[0-9a-f]{16}$")]
_MAX_REQUEST_LIFETIME = timedelta(minutes=10)


def existing_resources_digest(resources: object) -> str:
    """Bind the canonical kind/name/UID inventory without exposing it to the Hub."""

    return "sha256:" + canonical_digest(resources)


class NativeScopeTransitionRequest(BaseModel):
    """Installation-signed request for a Hub decision, not permission to change local state."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-request.v1"]
    request_id: UUID
    installation_id: PathId
    old_entity_id: PathId
    new_entity_id: PathId
    old_scope_digest: Digest
    new_scope_digest: Digest
    old_reported_state_digest: HexDigest
    ownership_claim_digest: Digest
    recovery_request_digest: Digest
    recovered_identity_key_id: InstallationKeyId
    existing_resources_digest: Digest
    requested_at: AwareDatetime
    expires_at: AwareDatetime
    confirmation: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        if (
            self.old_entity_id == self.new_entity_id
            or self.old_scope_digest == self.new_scope_digest
            or not timedelta(0) < self.expires_at - self.requested_at <= _MAX_REQUEST_LIFETIME
            or self.confirmation != self.required_confirmation
        ):
            raise ValueError("native transition request is invalid")
        return self

    @property
    def required_confirmation(self) -> str:
        return (
            f"transition native scope {self.installation_id} "
            f"{self.old_scope_digest} {self.new_scope_digest}"
        )

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))

    def require_current(self, now: datetime) -> None:
        if now.utcoffset() is None or not self.requested_at <= now < self.expires_at:
            raise ValueError("native transition request is not current")


class SignedNativeScopeTransitionRequest(BaseModel):
    """Proof that the recovered installation identity requested the exact transition."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request: NativeScopeTransitionRequest
    installation_proof: Annotated[str, StringConstraints(min_length=88, max_length=88)]

    @model_validator(mode="after")
    def validate_proof_encoding(self) -> Self:
        _signature_bytes(self.installation_proof, label="installation proof")
        return self

    def verify(self, public_key: bytes) -> bool:
        if installation_key_id(public_key) != self.request.recovered_identity_key_id:
            return False
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                _signature_bytes(self.installation_proof, label="installation proof"),
                self.request.payload,
            )
        except (InvalidSignature, ValueError):
            return False
        return True


class NativeScopeTransitionApproval(BaseModel):
    """Hub decision over recovery, accepted ownership, state, and the absence of an open Plan."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-approval.v1"]
    request: SignedNativeScopeTransitionRequest
    profile: Literal["full-authority-development"]
    approved_by: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9@._ -]{0,127}$")]
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    recovery_audit_digest: Digest
    ownership_audit_digest: Digest
    hub_key_id: HubKeyId
    hub_key_epoch: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        if (
            self.approved_at < self.request.request.requested_at
            or self.expires_at != self.request.request.expires_at
        ):
            raise ValueError("native transition approval interval is invalid")
        return self

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))

    def require_current(self, now: datetime) -> None:
        if now.utcoffset() is None or not self.approved_at <= now < self.expires_at:
            raise ValueError("native transition approval is not current")


class SignedNativeScopeTransitionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    approval: NativeScopeTransitionApproval
    hub_signature: Annotated[str, StringConstraints(min_length=88, max_length=88)]

    @model_validator(mode="after")
    def validate_signature_encoding(self) -> Self:
        _signature_bytes(self.hub_signature, label="Hub signature")
        return self

    def verify(self, public_key: bytes, *, key_id: str, key_epoch: int) -> bool:
        approval = self.approval
        if (
            approval.hub_key_id != key_id
            or approval.hub_key_epoch != key_epoch
            or hub_key_id(public_key) != key_id
        ):
            return False
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                _signature_bytes(self.hub_signature, label="Hub signature"),
                approval.payload,
            )
        except (InvalidSignature, ValueError):
            return False
        return True


def sign_transition_request(
    request: NativeScopeTransitionRequest, key: Ed25519PrivateKey
) -> SignedNativeScopeTransitionRequest:
    return SignedNativeScopeTransitionRequest(
        request=request,
        installation_proof=base64.b64encode(key.sign(request.payload)).decode("ascii"),
    )


def sign_transition_approval(
    approval: NativeScopeTransitionApproval, key: Ed25519PrivateKey
) -> SignedNativeScopeTransitionApproval:
    return SignedNativeScopeTransitionApproval(
        approval=approval,
        hub_signature=base64.b64encode(key.sign(approval.payload)).decode("ascii"),
    )


def hub_key_id(public_key: bytes) -> str:
    return "hub-" + hashlib.sha256(public_key).hexdigest()[:16]


def _signature_bytes(value: str, *, label: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"{label} encoding is invalid") from error
    if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{label} must contain canonical Ed25519 bytes")
    return decoded
