"""Ed25519 license verifier and issuer-key custody tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fdai.core.capability_catalog import default_capability_catalog
from fdai.core.licensing import LicenseStatus, encode_license_token, resolve_entitlement
from fdai.delivery.trust import (
    Ed25519LicenseVerifier,
    license_public_key_pem,
    private_key_matches_public_key,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _key_pair() -> tuple[Ed25519PrivateKey, bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, private_pem, public_pem


def test_verifier_accepts_only_the_matching_signature() -> None:
    signer, _private_pem, public_pem = _key_pair()
    other, _other_private_pem, _other_public_pem = _key_pair()
    document = b"canonical-license-document"
    verifier = Ed25519LicenseVerifier(public_pem)

    assert verifier.verify(document, signer.sign(document)) is True
    assert verifier.verify(document, other.sign(document)) is False


def test_private_key_match_requires_the_matching_owner_only_key(tmp_path: Path) -> None:
    _signer, private_pem, public_pem = _key_pair()
    _other, _other_private_pem, other_public_pem = _key_pair()
    private_path = tmp_path / "integrity-signing-key.pem"
    private_path.write_bytes(private_pem)
    private_path.chmod(0o600)

    assert private_key_matches_public_key(private_path, public_pem) is True
    assert private_key_matches_public_key(private_path, other_public_pem) is False

    private_path.chmod(0o644)
    with pytest.raises(PermissionError, match="mode 0600"):
        private_key_matches_public_key(private_path, public_pem)


def test_packaged_public_key_is_a_valid_ed25519_key() -> None:
    verifier = Ed25519LicenseVerifier(license_public_key_pem())

    assert verifier.verify(b"not-signed", b"x" * 64) is False


def test_packaged_key_is_the_tracked_upstream_integrity_key() -> None:
    tracked = _REPO_ROOT / "security/integrity/upstream-signing-key.pub"

    assert license_public_key_pem() == tracked.read_bytes()


def test_signed_integrity_manifest_never_resolves_as_a_license_token() -> None:
    integrity = _REPO_ROOT / "security/integrity"
    manifest = (integrity / "manifest.json").read_bytes()
    signature = base64.b64decode((integrity / "manifest.json.sig").read_bytes())

    # One key signs both, so only the document shape keeps the two domains apart.
    assert Ed25519LicenseVerifier(license_public_key_pem()).verify(manifest, signature)

    signer, _private_pem, public_pem = _key_pair()
    manifest_shaped = json.dumps(
        {
            "algorithm": "sha256",
            "file_count": 1,
            "files": {"services/core-control-plane/src/fdai/core/example.py": "a" * 64},
            "generated_at": "2026-10-01T00:00:00Z",
            "surface": ["services/core-control-plane/src/fdai/core/"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    token = encode_license_token(manifest_shaped, signer.sign(manifest_shaped))

    entitlement = resolve_entitlement(
        catalog=default_capability_catalog(),
        token=token,
        verifier=Ed25519LicenseVerifier(public_pem),
        now=datetime(2026, 10, 1, tzinfo=UTC),
        require_license=True,
    )

    assert entitlement.status is LicenseStatus.UNTRUSTED
    assert "operations.typed-mutation" not in entitlement.available_capability_ids
