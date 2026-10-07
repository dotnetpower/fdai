"""Ed25519 Hub signing keys for Lifecycle Plans.

Lifecycle I0 uses development keys that are valid only in the full-authority development
profile's dedicated test scope (#1947). Keys are generated locally and stored outside the
repository; no key material is committed.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fdai_deployment_cli.lifecycle_plan import SignatureVerifier


def key_id_for(public_key: Ed25519PublicKey) -> str:
    """Derive a stable key id from the raw public key bytes."""

    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "hub-" + hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class HubSigningKey:
    """One Hub key at one epoch."""

    private_key: Ed25519PrivateKey
    epoch: int

    def __post_init__(self) -> None:
        if isinstance(self.epoch, bool) or self.epoch < 1:
            raise ValueError("Hub key epoch must be a positive integer")

    @property
    def key_id(self) -> str:
        return key_id_for(self.private_key.public_key())

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self.private_key.public_key()

    def sign(self, payload: bytes) -> bytes:
        return self.private_key.sign(payload)


def generate_development_key(private_path: Path) -> Path:
    """Write a new private key with mode 0600 and its public key next to it."""

    if private_path.exists():
        raise FileExistsError(f"refusing to overwrite {private_path}")
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    public_path = private_path.with_suffix(".pub.pem")
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return public_path


def load_signing_key(private_path: Path, *, epoch: int) -> HubSigningKey:
    """Load an unencrypted PKCS8 Ed25519 private key that only its owner can read."""

    mode = stat.S_IMODE(private_path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError("Hub private key must not be readable by group or others")
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Hub key must be an Ed25519 private key")
    return HubSigningKey(private_key=key, epoch=epoch)


def load_public_key(public_path: Path) -> Ed25519PublicKey:
    """Load one PEM Ed25519 public key."""

    key = serialization.load_pem_public_key(public_path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Hub public key must be Ed25519")
    return key


def signature_verifier(public_keys: Mapping[str, Ed25519PublicKey]) -> SignatureVerifier:
    """Return a verifier that accepts only signatures by one of the named public keys."""

    keys = dict(public_keys)

    def verify(key_id: str, payload: bytes, signature: bytes) -> bool:
        public_key = keys.get(key_id)
        if public_key is None:
            return False
        try:
            public_key.verify(signature, payload)
        except InvalidSignature:
            return False
        return True

    return verify
