"""Ed25519 verifiers built from public key files.

Lifecycle I0 uses development test keys generated outside the repository (#1947). Only public
keys are read here; private keys never enter the agent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# Verifies ``(payload, signature)`` for one signer, such as the vendor release key.
type ArtifactVerifier = Callable[[bytes, bytes], bool]

_MAX_PUBLIC_KEY_BYTES = 16 * 1024


def load_ed25519_public_key(path: Path) -> Ed25519PublicKey:
    """Load one PEM Ed25519 public key or raise ``ValueError``."""

    try:
        if path.stat().st_size > _MAX_PUBLIC_KEY_BYTES:
            raise ValueError("public key file is too large")
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f"public key file is unreadable: {type(error).__name__}") from error
    try:
        key = load_pem_public_key(data)
    except (ValueError, UnsupportedAlgorithm) as error:
        raise ValueError("public key file is not a PEM public key") from error
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public key MUST be Ed25519")
    return key


class Ed25519ArtifactVerifier:
    """Verify detached Ed25519 signatures for one signer."""

    def __init__(self, public_key: Ed25519PublicKey) -> None:
        self._public_key = public_key

    @classmethod
    def from_file(cls, path: Path) -> Ed25519ArtifactVerifier:
        return cls(load_ed25519_public_key(path))

    def __call__(self, payload: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, payload)
        except InvalidSignature:
            return False
        return True


class Ed25519HubKeyring:
    """Plan ``SignatureVerifier`` that resolves ``hub_key_id`` to a configured public key.

    An unknown key id fails verification. Revocation and epoch checks stay in admission.
    """

    def __init__(self, keys: Mapping[str, Ed25519PublicKey]) -> None:
        self._verifiers = {key_id: Ed25519ArtifactVerifier(key) for key_id, key in keys.items()}

    def __call__(self, key_id: str, payload: bytes, signature: bytes) -> bool:
        verifier = self._verifiers.get(key_id)
        return verifier is not None and verifier(payload, signature)
