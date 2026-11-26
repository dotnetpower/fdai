"""Ed25519 adapters for remediation-pack signing.

The signer reads one owner-only (mode 0600) PEM private key through the hardened key-file
boundary and never exposes key bytes. The verifier holds trusted public keys indexed by the
same key id the stdlib pack helper computes, so FDAI and developers agree on key identity.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from fdai.core.security.code_findings.ed25519_verify import key_id as derive_key_id
from fdai.delivery.trust.key_file import read_key_file


def _raw_public(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)


class Ed25519PackSigner:
    """Sign pack manifests with an Ed25519 key loaded from an owner-only PEM file."""

    __slots__ = ("_key", "_key_id")

    def __init__(self, private_key_path: Path) -> None:
        pem = read_key_file(private_key_path, private=True)
        try:
            key = load_pem_private_key(pem, password=None)
        except (TypeError, ValueError) as exc:
            raise ValueError("pack signing key is invalid") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("pack signing key must be Ed25519")
        self._key = key
        self._key_id = derive_key_id(_raw_public(key.public_key()))

    @property
    def key_id(self) -> str:
        return self._key_id

    def public_key_pem(self) -> bytes:
        """Return the public key that developers pin to verify packs."""
        return self._key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)


class Ed25519PackVerifier:
    """Verify pack signatures against a fixed set of trusted Ed25519 public keys."""

    __slots__ = ("_keys",)

    def __init__(self, public_keys_pem: Iterable[bytes]) -> None:
        keys: dict[str, Ed25519PublicKey] = {}
        for pem in public_keys_pem:
            try:
                key = load_pem_public_key(pem)
            except (TypeError, ValueError) as exc:
                raise ValueError("trusted pack public key is invalid") from exc
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("trusted pack public key must be Ed25519")
            keys[derive_key_id(_raw_public(key))] = key
        self._keys = keys

    def verify(self, message: bytes, signature: bytes, key_id: str) -> bool:
        key = self._keys.get(key_id)
        if key is None:
            return False
        try:
            key.verify(signature, message)
        except InvalidSignature:
            return False
        return True


__all__ = ["Ed25519PackSigner", "Ed25519PackVerifier"]
