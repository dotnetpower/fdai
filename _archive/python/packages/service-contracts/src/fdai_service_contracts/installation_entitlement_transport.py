"""Purpose-distinct confidentiality for an existing issuer-signed entitlement.

This data-only codec performs no I/O, trust registration, license verification or
activation. Decryption returns the original untrusted token bytes, never a grant.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENTITLEMENT_CARRIER_SCHEMA: Final = "fdai.lifecycle.entitlement-carrier.v1"
ENTITLEMENT_CARRIER_PURPOSE: Final = "fdai.installation-entitlement.transport.v1"
MAX_ENTITLEMENT_CARRIER_BYTES: Final = 16_384
MAX_ENTITLEMENT_TOKEN_BYTES: Final = 8192
_DOMAIN: Final = ENTITLEMENT_CARRIER_PURPOSE.encode("ascii") + b"\x00"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_FIELDS = frozenset(
    {
        "schema_version",
        "purpose",
        "installation_binding",
        "deployment_binding",
        "recipient_fingerprint",
        "ephemeral_public_key",
        "nonce",
        "ciphertext",
    }
)


class EntitlementTransportError(ValueError):
    """The carrier cannot establish exact recipient, purpose or byte integrity."""


@dataclass(frozen=True, slots=True)
class EntitlementRecipient:
    installation_binding: str
    deployment_binding: str
    fingerprint: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _DIGEST.fullmatch(value) is None
            for value in (self.installation_binding, self.deployment_binding, self.fingerprint)
        ):
            raise EntitlementTransportError("entitlement recipient requires exact SHA-256 bindings")


def entitlement_recipient(
    public_key: X25519PublicKey, *, installation_binding: str, deployment_binding: str
) -> EntitlementRecipient:
    """Bind an independently supplied encryption key, without inferring key purpose or authority."""
    if not isinstance(public_key, X25519PublicKey):
        raise EntitlementTransportError("entitlement recipient requires an X25519 encryption key")
    return EntitlementRecipient(
        installation_binding,
        deployment_binding,
        hashlib.sha256(_public_bytes(public_key)).hexdigest(),
    )


def seal_entitlement_token(
    token: bytes,
    *,
    recipient: EntitlementRecipient,
    public_key: X25519PublicKey,
) -> bytes:
    """Seal bounded original token bytes; their issuer and eligibility are not verified."""
    if not isinstance(token, bytes) or not 1 <= len(token) <= MAX_ENTITLEMENT_TOKEN_BYTES:
        raise EntitlementTransportError("entitlement token is empty or exceeds 8192 bytes")
    actual = entitlement_recipient(
        public_key,
        installation_binding=recipient.installation_binding,
        deployment_binding=recipient.deployment_binding,
    )
    if actual != recipient:
        raise EntitlementTransportError("entitlement recipient key does not match its binding")
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = _public_bytes(ephemeral.public_key())
    nonce = os.urandom(12)
    header = _header(recipient, ephemeral_public, nonce)
    key = _derive(ephemeral.exchange(public_key), _public_bytes(public_key), ephemeral_public)
    ciphertext = AESGCM(key).encrypt(nonce, token, _canonical(header))
    result = _canonical({**header, "ciphertext": _encode(ciphertext)})
    if len(result) > MAX_ENTITLEMENT_CARRIER_BYTES:
        raise EntitlementTransportError("entitlement carrier exceeds 16384 bytes")
    return result


def unseal_entitlement_token(
    carrier: bytes,
    *,
    recipient: EntitlementRecipient,
    private_key: X25519PrivateKey,
) -> bytes:
    """Return original untrusted bytes only after exact recipient and AEAD verification."""
    if not isinstance(private_key, X25519PrivateKey):
        raise EntitlementTransportError("entitlement recipient requires an X25519 private key")
    if not isinstance(carrier, bytes) or not 1 <= len(carrier) <= MAX_ENTITLEMENT_CARRIER_BYTES:
        raise EntitlementTransportError("entitlement carrier is empty or exceeds 16384 bytes")
    try:
        value = json.loads(carrier)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EntitlementTransportError(
            "entitlement carrier is not bounded canonical JSON"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != _FIELDS
        or any(not isinstance(item, str) for item in value.values())
        or _canonical(value) != carrier
    ):
        raise EntitlementTransportError("entitlement carrier fields or encoding are not canonical")
    actual = entitlement_recipient(
        private_key.public_key(),
        installation_binding=recipient.installation_binding,
        deployment_binding=recipient.deployment_binding,
    )
    if actual != recipient:
        raise EntitlementTransportError("entitlement private key does not match its recipient")
    if (
        value["schema_version"] != ENTITLEMENT_CARRIER_SCHEMA
        or value["purpose"] != ENTITLEMENT_CARRIER_PURPOSE
        or value["installation_binding"] != recipient.installation_binding
        or value["deployment_binding"] != recipient.deployment_binding
        or value["recipient_fingerprint"] != recipient.fingerprint
    ):
        raise EntitlementTransportError("entitlement carrier purpose or recipient does not match")
    ephemeral_public = _decode(value["ephemeral_public_key"])
    nonce = _decode(value["nonce"])
    ciphertext = _decode(value["ciphertext"])
    if len(ephemeral_public) != 32 or len(nonce) != 12 or not 17 <= len(ciphertext) <= 8208:
        raise EntitlementTransportError(
            "entitlement carrier cryptographic fields are out of bounds"
        )
    header = _header(recipient, ephemeral_public, nonce)
    try:
        shared = private_key.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
        key = _derive(shared, _public_bytes(private_key.public_key()), ephemeral_public)
        token = AESGCM(key).decrypt(nonce, ciphertext, _canonical(header))
    except (InvalidTag, ValueError) as exc:
        raise EntitlementTransportError("entitlement carrier authentication failed") from exc
    if not 1 <= len(token) <= MAX_ENTITLEMENT_TOKEN_BYTES:
        raise EntitlementTransportError("decrypted entitlement token is out of bounds")
    return token


def _header(
    recipient: EntitlementRecipient, ephemeral_public: bytes, nonce: bytes
) -> dict[str, str]:
    return {
        "schema_version": ENTITLEMENT_CARRIER_SCHEMA,
        "purpose": ENTITLEMENT_CARRIER_PURPOSE,
        "installation_binding": recipient.installation_binding,
        "deployment_binding": recipient.deployment_binding,
        "recipient_fingerprint": recipient.fingerprint,
        "ephemeral_public_key": _encode(ephemeral_public),
        "nonce": _encode(nonce),
    }


def _public_bytes(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _derive(shared: bytes, recipient: bytes, ephemeral: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_DOMAIN + recipient + ephemeral
    ).derive(shared)


def _canonical(value: dict[str, str]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EntitlementTransportError("entitlement carrier field is not base64url") from exc
    if _encode(result) != value:
        raise EntitlementTransportError("entitlement carrier field is not canonical base64url")
    return result
