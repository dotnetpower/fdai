"""Ed25519 observation-context authentication for Azure deployments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    ObservationVerificationReceipt,
)

_MAX_ISSUE_DELAY = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class AzureObservationContextIdentity:
    """Credential lineage attached to one deployment-owned verification key."""

    observer_credential_lineage: str
    executor_credential_lineage: str
    source_credential_lineage: str
    verifier_identity: str

    def __post_init__(self) -> None:
        values = (
            self.observer_credential_lineage,
            self.executor_credential_lineage,
            self.source_credential_lineage,
            self.verifier_identity,
        )
        if any(not value.strip() or len(value) > 512 for value in values):
            raise ValueError(
                "Azure observation credential identities MUST be bounded and non-empty"
            )
        _require_distinct(
            "Azure configured observation credential lineages",
            (
                self.observer_credential_lineage,
                self.executor_credential_lineage,
                self.source_credential_lineage,
            ),
        )


class AzureEd25519ObservationContextIssuer:
    """Sign an observation context with a deployment-owned Ed25519 key."""

    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey,
        identity: AzureObservationContextIdentity,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._private_key = private_key
        self._identity = identity
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._verifier_credential_lineage = _public_key_lineage(private_key.public_key())

    async def issue(
        self,
        *,
        evidence: EffectObservationEnvelope,
    ) -> AuthenticatedObservationContext:
        """Issue a receipt that binds the exact observation and credential lineages."""

        if evidence.source_authority not in {
            EffectEvidenceAuthority.PROVIDER,
            EffectEvidenceAuthority.TELEMETRY,
        }:
            raise ValueError("Azure observation source is not independently authoritative")
        verified_at = _aware_utc(self._clock(), name="verification clock")
        recorded_at = evidence.recorded_at.astimezone(UTC)
        if not recorded_at <= verified_at <= recorded_at + _MAX_ISSUE_DELAY:
            raise ValueError("Azure observation verification time is outside the issue window")
        identities = (
            evidence.observer_identity,
            evidence.execution_identity,
            evidence.source_identity,
            self._identity.verifier_identity,
        )
        lineages = (
            self._identity.observer_credential_lineage,
            self._identity.executor_credential_lineage,
            self._identity.source_credential_lineage,
            self._verifier_credential_lineage,
        )
        _require_distinct("Azure observation identities", identities)
        _require_distinct("Azure observation credential lineages", lineages)
        signature = _encode_signature(
            self._private_key.sign(
                _signature_payload(
                    evidence=evidence,
                    source_authority=evidence.source_authority,
                    observer_identity=evidence.observer_identity,
                    observer_credential_lineage=self._identity.observer_credential_lineage,
                    executor_identity=evidence.execution_identity,
                    executor_credential_lineage=self._identity.executor_credential_lineage,
                    source_identity=evidence.source_identity,
                    source_credential_lineage=self._identity.source_credential_lineage,
                    verifier_identity=self._identity.verifier_identity,
                    verifier_credential_lineage=self._verifier_credential_lineage,
                    verified_at=verified_at,
                )
            )
        )
        receipt = ObservationVerificationReceipt.create(
            observation_id=evidence.observation_id,
            observation_digest=evidence.content_digest(),
            verifier_identity=self._identity.verifier_identity,
            verifier_credential_lineage=self._verifier_credential_lineage,
            verified_at=verified_at,
            signature_algorithm="ed25519",
            signature=signature,
        )
        return AuthenticatedObservationContext(
            source_authority=evidence.source_authority,
            observer_identity=evidence.observer_identity,
            observer_credential_lineage=self._identity.observer_credential_lineage,
            executor_identity=evidence.execution_identity,
            executor_credential_lineage=self._identity.executor_credential_lineage,
            source_identity=evidence.source_identity,
            source_credential_lineage=self._identity.source_credential_lineage,
            verification_receipt=receipt,
            signature_verified=True,
        )


class AzureEd25519ObservationContextAuthenticator:
    """Verify a claimed observation context using only the deployment public key."""

    def __init__(self, *, public_key: Ed25519PublicKey) -> None:
        self._public_key = public_key
        self._verifier_credential_lineage = _public_key_lineage(public_key)

    async def authenticate(
        self,
        *,
        evidence: EffectObservationEnvelope,
        claimed_context: AuthenticatedObservationContext,
    ) -> AuthenticatedObservationContext:
        """Return the unchanged context only after exact Ed25519 verification."""

        receipt = claimed_context.verification_receipt
        if receipt.verifier_credential_lineage != self._verifier_credential_lineage:
            raise ValueError("Azure observation verifier key lineage does not match deployment")
        if (
            receipt.observation_id != evidence.observation_id
            or receipt.observation_digest != evidence.content_digest()
        ):
            raise ValueError("Azure observation receipt does not bind exact evidence")
        verified_at = receipt.verified_at.astimezone(UTC)
        recorded_at = evidence.recorded_at.astimezone(UTC)
        if not recorded_at <= verified_at <= recorded_at + _MAX_ISSUE_DELAY:
            raise ValueError("Azure observation verification time is outside the issue window")
        payload = _signature_payload(
            evidence=evidence,
            source_authority=claimed_context.source_authority,
            observer_identity=claimed_context.observer_identity,
            observer_credential_lineage=claimed_context.observer_credential_lineage,
            executor_identity=claimed_context.executor_identity,
            executor_credential_lineage=claimed_context.executor_credential_lineage,
            source_identity=claimed_context.source_identity,
            source_credential_lineage=claimed_context.source_credential_lineage,
            verifier_identity=receipt.verifier_identity,
            verifier_credential_lineage=receipt.verifier_credential_lineage,
            verified_at=verified_at,
        )
        try:
            self._public_key.verify(_decode_signature(receipt.signature), payload)
        except InvalidSignature as exc:
            raise ValueError("Azure observation context signature is invalid") from exc
        return claimed_context


def build_azure_observation_context_pair(
    *,
    private_key_seed: str,
    identity: AzureObservationContextIdentity,
    clock: Callable[[], datetime] | None = None,
) -> tuple[
    AzureEd25519ObservationContextIssuer,
    AzureEd25519ObservationContextAuthenticator,
]:
    """Build a signer and public-key-only authenticator from one Key Vault seed."""

    private_key = Ed25519PrivateKey.from_private_bytes(_decode_seed(private_key_seed))
    return (
        AzureEd25519ObservationContextIssuer(
            private_key=private_key,
            identity=identity,
            clock=clock,
        ),
        AzureEd25519ObservationContextAuthenticator(public_key=private_key.public_key()),
    )


def _signature_payload(
    *,
    evidence: EffectObservationEnvelope,
    source_authority: EffectEvidenceAuthority,
    observer_identity: str,
    observer_credential_lineage: str,
    executor_identity: str,
    executor_credential_lineage: str,
    source_identity: str,
    source_credential_lineage: str,
    verifier_identity: str,
    verifier_credential_lineage: str,
    verified_at: datetime,
) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "observation_id": evidence.observation_id,
            "observation_digest": evidence.content_digest(),
            "source_authority": source_authority.value,
            "observer_identity": observer_identity,
            "observer_credential_lineage": observer_credential_lineage,
            "executor_identity": executor_identity,
            "executor_credential_lineage": executor_credential_lineage,
            "source_identity": source_identity,
            "source_credential_lineage": source_credential_lineage,
            "verifier_identity": verifier_identity,
            "verifier_credential_lineage": verifier_credential_lineage,
            "verified_at": _aware_utc(verified_at, name="verified_at").isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _decode_seed(value: str) -> bytes:
    if len(value) != 43 or "=" in value or any(character not in _BASE64URL for character in value):
        raise ValueError("Azure observation signing seed MUST be unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Azure observation signing seed MUST be unpadded base64url") from exc
    if len(decoded) != 32 or _encode_base64url(decoded) != value:
        raise ValueError("Azure observation signing seed MUST encode exactly 32 bytes")
    return decoded


def _decode_signature(value: str) -> bytes:
    if not value.startswith("base64:"):
        raise ValueError("Azure observation signature is malformed")
    encoded = value.removeprefix("base64:")
    try:
        signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Azure observation signature is malformed") from exc
    if len(signature) != 64 or _encode_base64url(signature) != encoded:
        raise ValueError("Azure observation signature is malformed")
    return signature


def _encode_signature(value: bytes) -> str:
    return f"base64:{_encode_base64url(value)}"


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _public_key_lineage(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return f"ed25519:sha256:{hashlib.sha256(raw).hexdigest()}"


def _aware_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Azure observation {name} MUST be timezone-aware")
    return value.astimezone(UTC)


def _require_distinct(label: str, values: tuple[str, ...]) -> None:
    normalized = {value.strip().casefold() for value in values}
    if len(normalized) != len(values):
        raise ValueError(f"{label} MUST be distinct")


_BASE64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")

__all__ = [
    "AzureEd25519ObservationContextAuthenticator",
    "AzureEd25519ObservationContextIssuer",
    "AzureObservationContextIdentity",
    "build_azure_observation_context_pair",
]
