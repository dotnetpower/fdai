"""Ed25519 verification adapter for capability-license documents."""

from __future__ import annotations

import hmac
from importlib.resources import files
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from fdai.delivery.trust.key_file import read_key_file

_PUBLIC_KEY_RESOURCE = "upstream-signing-key.pub"


class Ed25519LicenseVerifier:
    """Verify canonical license bytes against one packaged Ed25519 key."""

    __slots__ = ("_public_key",)

    def __init__(self, public_key_pem: bytes) -> None:
        self._public_key = _load_public_key(public_key_pem)

    def verify(self, document: bytes, signature: bytes) -> bool:
        """Return false for an invalid signature without exposing key data."""

        try:
            self._public_key.verify(signature, document)
        except InvalidSignature:
            return False
        return True


def license_public_key_pem() -> bytes:
    """Return the upstream integrity public key, Core's only license verification key."""

    return files("fdai.delivery.trust").joinpath(_PUBLIC_KEY_RESOURCE).read_bytes()


def private_key_matches_public_key(path: Path, public_key_pem: bytes) -> bool:
    """Prove that an owner-only local Ed25519 key matches the public key.

    The private bytes are read once through the hardened descriptor boundary,
    used only to derive public bytes, and never returned or logged.
    """

    private_key_pem = read_key_file(path, private=True)
    try:
        private_key = load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("license issuer private key is invalid") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("license issuer private key MUST be Ed25519")
    public_key = _load_public_key(public_key_pem)
    derived = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    expected = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return hmac.compare_digest(derived, expected)


def _load_public_key(public_key_pem: bytes) -> Ed25519PublicKey:
    try:
        public_key = load_pem_public_key(public_key_pem)
    except (TypeError, ValueError) as exc:
        raise ValueError("license public key is invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("license public key MUST be Ed25519")
    return public_key


__all__ = [
    "Ed25519LicenseVerifier",
    "license_public_key_pem",
    "private_key_matches_public_key",
]
