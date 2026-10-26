"""Role-separated public configuration trust; private material never crosses this boundary."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from fdai_deployment_cli.contracts import canonical_bytes
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from fdai_lifecycle_hub import schemas
from fdai_lifecycle_hub.enrollment import PROOF_CLOCK_WINDOW
from fdai_lifecycle_hub.signing import installation_key_id, verify_key_proof

PublicKey = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_ED25519_FIELD = 2**255 - 19
_ED25519_D = -121665 * pow(121666, _ED25519_FIELD - 2, _ED25519_FIELD) % _ED25519_FIELD


def _validate_signing_public_key(raw: bytes) -> None:
    """Reject noncanonical/off-curve/small-order Edwards points before possession proofs.

    Signature verification alone accepts identity-point forgeries in the crypto provider.
    Public y-coordinate doubling checks [8]P != identity without deriving encryption keys.
    """
    encoded = int.from_bytes(raw, "little")
    y = encoded & (2**255 - 1)
    field = _ED25519_FIELD
    if len(raw) != 32 or y >= field:
        raise ValueError("Configuration signing public key is invalid.")
    squared = y * y % field
    denominator = (_ED25519_D * squared + 1) % field
    x_squared = (squared - 1) * pow(denominator, field - 2, field) % field
    if (
        denominator == 0
        or pow(x_squared, (field - 1) // 2, field) not in {0, 1}
        or (x_squared == 0 and encoded >> 255)
    ):
        raise ValueError("Configuration signing public key is invalid.")
    for _ in range(3):
        squared = y * y % field
        quartic = _ED25519_D * squared * squared % field
        denominator = (1 + 2 * _ED25519_D * squared - quartic) % field
        if denominator == 0:
            raise ValueError("Configuration signing public key is invalid.")
        y = (quartic + 2 * squared - 1) * pow(denominator, field - 2, field) % field
    if y == 1:
        raise ValueError("Configuration signing public key has small order.")


class KeyBindingError(ValueError):
    """A bounded, public denial reason, without input bytes."""


class ConfigurationKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["fdai.configuration-keys.v1"]
    installation_id: schemas.Identifier
    installation_identity_key_id: schemas.InstallationKeyId
    requester: schemas.Actor
    request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    version: Annotated[int, Field(strict=True, ge=1)]
    predecessor_digest: schemas.Digest | None
    signing_algorithm: Literal["Ed25519"]
    configuration_signing_key: PublicKey
    encryption_algorithm: Literal["X25519"]
    installation_encryption_key: PublicKey
    requested_at: AwareDatetime
    approval_expires_at: AwareDatetime
    binding_expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_roles_and_times(self) -> ConfigurationKeyRequest:
        _validate_signing_public_key(bytes.fromhex(self.configuration_signing_key))
        if self.configuration_signing_key == self.installation_encryption_key:
            raise ValueError("Configuration signing and encryption roles must be distinct.")
        if not (
            self.requested_at
            < self.approval_expires_at
            <= self.requested_at + timedelta(minutes=10)
            < self.binding_expires_at
            <= self.requested_at + timedelta(days=90)
        ):
            raise ValueError("Configuration binding validity is outside its bounds.")
        recipient = X25519PublicKey.from_public_bytes(
            bytes.fromhex(self.installation_encryption_key)
        )
        try:
            X25519PrivateKey.generate().exchange(recipient)
        except ValueError:
            raise ValueError("Configuration encryption public key is invalid.") from None
        return self

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @property
    def digest(self) -> str:
        return public_digest(self.payload)

    def verify(
        self,
        *,
        identity: bytes,
        identity_proof: bytes,
        signer_proof: bytes,
        actor: str,
        now: datetime,
    ) -> None:
        if actor != self.requester:
            raise KeyBindingError("configuration_requester_mismatch")
        if self.installation_identity_key_id != installation_key_id(identity) or identity.hex() in {
            self.configuration_signing_key,
            self.installation_encryption_key,
        }:
            raise KeyBindingError("configuration_identity_mismatch")
        if abs(now - self.requested_at) > PROOF_CLOCK_WINDOW or now >= self.approval_expires_at:
            raise KeyBindingError("configuration_request_expired")
        try:
            _validate_signing_public_key(identity)
            if not verify_key_proof(
                public_key=identity, payload=self.payload, signature=identity_proof
            ):
                raise ValueError("Configuration identity proof is invalid.")
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(self.configuration_signing_key)
            ).verify(signer_proof, self.payload)
        except (InvalidSignature, ValueError):
            raise KeyBindingError("configuration_proof_invalid") from None


class SignedKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signed_payload: schemas.Base64
    identity_proof: schemas.Base64
    signer_proof: schemas.Base64

    def parsed(self) -> ConfigurationKeyRequest:
        result = ConfigurationKeyRequest.model_validate_json(self.signed_payload)
        if result.payload != self.signed_payload:
            raise KeyBindingError("configuration_request_not_canonical")
        return result


class DevelopmentIdentityRecoveryRequest(BaseModel):
    """One exact replacement identity selected by protected development configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["fdai.development-identity-recovery.v1"]
    installation_id: schemas.Identifier
    scope: Annotated[str, Field(min_length=1, max_length=256)]
    request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    previous_identity_key_id: schemas.InstallationKeyId
    replacement_identity_public_key: PublicKey
    requested_at: AwareDatetime
    confirmation: str

    @model_validator(mode="after")
    def validate_recovery(self) -> DevelopmentIdentityRecoveryRequest:
        replacement = bytes.fromhex(self.replacement_identity_public_key)
        _validate_signing_public_key(replacement)
        replacement_key_id = installation_key_id(replacement)
        if self.previous_identity_key_id == replacement_key_id or self.confirmation != (
            f"recover installation identity {self.installation_id} "
            f"{self.previous_identity_key_id} {replacement_key_id}"
        ):
            raise ValueError("Development identity recovery confirmation differs.")
        return self

    @property
    def payload(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @property
    def digest(self) -> str:
        return public_digest(self.payload)

    @property
    def replacement_key_id(self) -> str:
        return installation_key_id(bytes.fromhex(self.replacement_identity_public_key))

    def verify_possession(self, proof: bytes, *, now: datetime) -> None:
        if abs(now - self.requested_at) > PROOF_CLOCK_WINDOW:
            raise KeyBindingError("development_identity_recovery_expired")
        try:
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(self.replacement_identity_public_key)
            ).verify(proof, self.payload)
        except (InvalidSignature, ValueError):
            raise KeyBindingError("development_identity_recovery_proof_invalid") from None


class SignedDevelopmentIdentityRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signed_payload: schemas.Base64
    proof: schemas.Base64

    def parsed(self) -> DevelopmentIdentityRecoveryRequest:
        result = DevelopmentIdentityRecoveryRequest.model_validate_json(self.signed_payload)
        if result.payload != self.signed_payload:
            raise KeyBindingError("development_identity_recovery_not_canonical")
        return result


class KeyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_digest: schemas.Digest


def public_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()
