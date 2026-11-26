"""Bounded, identity-proven scope and import requests with no private key input."""

from __future__ import annotations

from base64 import b64decode
from datetime import datetime, timedelta
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_configuration_package import SignedConfigurationPackage
from fdai_deployment_cli.lifecycle_configuration_sealing import read_object
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from fdai_lifecycle_hub.configuration_keys import KeyBindingError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
EntityIdentifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
MAX_HISTORY_BYTES = 16 * 1024 * 1024


class ScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format: Literal["fdai.configuration-scope.v1"]
    installation_id: EntityIdentifier
    requester: str = Field(min_length=1, max_length=160)
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    release_version: str = Field(min_length=1, max_length=160)
    release_digest: Digest
    schema_digest: Digest
    entity_bindings: dict[EntityIdentifier, Digest] = Field(min_length=1, max_length=256)
    sealed_keys: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")]] = Field(
        max_length=256
    )
    requested_at: AwareDatetime
    approval_expires_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bounded(self) -> ScopeRequest:
        if (
            len(set(self.entity_bindings.values())) != len(self.entity_bindings)
            or sorted(set(self.sealed_keys)) != self.sealed_keys
            or not self.requested_at
            < self.approval_expires_at
            <= self.requested_at + timedelta(minutes=10)
            or not self.approval_expires_at
            < self.expires_at
            <= self.requested_at + timedelta(days=90)
        ):
            raise ValueError("configuration scope bounds are invalid")
        return self

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class ImportContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format: Literal["fdai.configuration-import.v1"]
    installation_id: EntityIdentifier
    requester: str = Field(min_length=1, max_length=160)
    package_digest: Digest
    container_digest: Digest
    binding_version: int = Field(ge=1)
    scope_digest: Digest
    predecessor_digest: Digest | None
    requested_at: AwareDatetime

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))


class SignedScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    signed_payload: str = Field(min_length=1, max_length=65536)
    identity_proof: str = Field(min_length=1, max_length=128)


class SignedImportRequest(SignedScopeRequest):
    signed_container: str = Field(min_length=1, max_length=4 * 1024 * 1024)


class ImportDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    digest: Digest
    receipt_digest: Digest


class ScopeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    digest: Digest


def decode(value: str) -> bytes:
    try:
        return b64decode(value, validate=True)
    except ValueError:
        raise KeyBindingError("configuration_encoding_invalid") from None


def verify_identity(payload: bytes, proof: bytes, identity: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(identity).verify(proof, payload)
    except (InvalidSignature, ValueError):
        raise KeyBindingError("configuration_identity_proof_invalid") from None


def fresh(requested: datetime, now: datetime) -> None:
    if abs(now - requested) > timedelta(minutes=5):
        raise KeyBindingError("configuration_request_expired")


def read_container(raw: bytes) -> SignedConfigurationPackage:
    """Retain caller's exact closed container bytes, but accept no embedded trust."""
    try:
        document = read_object(raw)
        if (
            set(document) != {"format", "payload", "signature"}
            or document["format"] != "fdai.lifecycle-configuration-file.v1"
            or not isinstance(document["payload"], str)
            or not isinstance(document["signature"], str)
        ):
            raise ValueError
        package = SignedConfigurationPackage(
            decode(document["payload"]), decode(document["signature"])
        )
        if len(package.payload) > 1024 * 1024 or len(package.signature) != 64:
            raise ValueError
        return package
    except ValueError:
        raise KeyBindingError("configuration_container_invalid") from None
