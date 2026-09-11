"""Package-pinned public roots for standalone deployment verification."""

from __future__ import annotations

from importlib.resources import files

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_TRUST_PACKAGE = "fdai_deployment_cli"
_TRUST_DIRECTORY = "trust"


def deployment_release_root_pem() -> bytes:
    """Return the public key that verifies complete deployment kits."""

    return _read("deployment-release-root.pub")


def deployment_bundle_root_pem() -> bytes:
    """Return the public key that verifies the deployment bundle inside a kit."""

    return _read("deployment-bundle-root.pub")


def license_public_key_pem() -> bytes:
    """Return the runtime capability-license verification key."""

    return _read("license-signing-key.pub")


def _read(name: str) -> bytes:
    resource = files(_TRUST_PACKAGE).joinpath(_TRUST_DIRECTORY, name)
    value = resource.read_bytes()
    if not value.startswith(b"-----BEGIN PUBLIC KEY-----\n") or len(value) > 65_536:
        raise ValueError("packaged deployment trust root is invalid")
    try:
        key = load_pem_public_key(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("packaged deployment trust root is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("packaged deployment trust root must be Ed25519")
    return value
