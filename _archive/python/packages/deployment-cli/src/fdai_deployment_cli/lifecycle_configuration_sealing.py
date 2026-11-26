"""Installation-only identifier encryption; no identity or enrollment authority."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration import validate_configuration_package_for_signing

_ALGORITHM = "X25519-HKDF-SHA256-AES256GCM"
_INFO = b"fdai.lifecycle-configuration.sealed.v1"


def encryption_key_digest(key: X25519PublicKey) -> str:
    """Identify an explicitly bound encryption key, never an Ed25519 identity key."""
    return hashlib.sha256(key.public_bytes_raw()).hexdigest()


def seal_identifiers(
    values: Mapping[str, object], recipient: X25519PublicKey, *, context: bytes
) -> dict[str, object]:
    """Scan plaintext before encryption and bind ciphertext to the signed revision context."""
    validate_configuration_package_for_signing(values)
    plaintext = canonical_bytes(values)
    ephemeral = X25519PrivateKey.generate()
    nonce = os.urandom(12)
    key = _derive_key(ephemeral, recipient, context)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, context)
    return {
        "algorithm": _ALGORITHM,
        "recipient_digest": encryption_key_digest(recipient),
        "ephemeral_key": _encode(ephemeral.public_key().public_bytes_raw()),
        "nonce": _encode(nonce),
        "ciphertext": _encode(ciphertext),
    }


def validate_sealed_identifiers(envelope: Mapping[str, object], *, recipient_digest: str) -> None:
    """Check the public envelope without decrypting or exposing identifier values."""
    if set(envelope) != {"algorithm", "recipient_digest", "ephemeral_key", "nonce", "ciphertext"}:
        raise ValueError("sealed identifier envelope fields are invalid")
    if envelope["algorithm"] != _ALGORITHM or envelope["recipient_digest"] != recipient_digest:
        raise ValueError("sealed identifier recipient or algorithm is invalid")
    if len(_decode(envelope["ephemeral_key"])) != 32 or len(_decode(envelope["nonce"])) != 12:
        raise ValueError("sealed identifier key or nonce length is invalid")
    if len(_decode(envelope["ciphertext"])) < 16:
        raise ValueError("sealed identifier ciphertext is invalid")


def open_identifiers(
    envelope: Mapping[str, object], recipient: X25519PrivateKey, *, context: bytes
) -> dict[str, object]:
    """Decrypt only inside the installation; a wrong key or changed revision fails closed."""
    validate_sealed_identifiers(
        envelope, recipient_digest=encryption_key_digest(recipient.public_key())
    )
    ephemeral = X25519PublicKey.from_public_bytes(_decode(envelope["ephemeral_key"]))
    key = _derive_key(recipient, ephemeral, context)
    try:
        plaintext = AESGCM(key).decrypt(
            _decode(envelope["nonce"]), _decode(envelope["ciphertext"]), context
        )
    except InvalidTag:
        raise ValueError("sealed identifier authentication failed") from None
    values = read_object(plaintext)
    validate_configuration_package_for_signing(values)
    return values


def read_object(payload: bytes) -> dict[str, object]:
    """Read strict JSON without duplicate fields, nonfinite numbers, or error-data leakage."""
    try:
        value: object = json.loads(
            payload, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("configuration package JSON is invalid") from None
    if not isinstance(value, dict):
        raise ValueError("configuration package JSON must be an object")
    return {str(key): item for key, item in value.items()}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = item
    return result


def _invalid_constant(value: str) -> object:
    raise ValueError("nonfinite JSON number")


def _derive_key(private: X25519PrivateKey, public: X25519PublicKey, context: bytes) -> bytes:
    try:
        shared = private.exchange(public)
    except ValueError:
        raise ValueError("installation encryption key is invalid") from None
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=hashlib.sha256(context).digest(), info=_INFO
    ).derive(shared)


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("sealed identifier encoding is invalid")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("sealed identifier encoding is invalid") from None
