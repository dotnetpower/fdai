"""Focused tests for signed deployment profile closures."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_deployment_cli.offline_kit import (
    MANIFEST_NAME,
    ROOT_MANIFEST_NAME,
    ROOT_SIGNATURE_NAME,
    OfflineKitVerificationError,
    build_root_manifest,
    verify_root_manifest,
)


def _public_pem(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _write_root(
    root: Path,
    key: Ed25519PrivateKey,
    *,
    kit_manifest_digest: str,
    profiles: list[str],
) -> None:
    manifest = build_root_manifest(
        kit_manifest_digest=kit_manifest_digest,
        profiles=profiles,
    )
    (root / ROOT_MANIFEST_NAME).write_bytes(manifest)
    (root / ROOT_SIGNATURE_NAME).write_bytes(key.sign(manifest))


def test_root_manifest_binds_sorted_profile_closure(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    kit_manifest = b'{"schema_version":"legacy-test"}'
    (tmp_path / MANIFEST_NAME).write_bytes(kit_manifest)
    _write_root(
        tmp_path,
        key,
        kit_manifest_digest=hashlib.sha256(kit_manifest).hexdigest(),
        profiles=["offline", "connected", "appliance", "offline"],
    )

    result = verify_root_manifest(
        tmp_path,
        release_root_pem=_public_pem(key),
        expected_profile="connected",
    )

    assert result.profiles == ("appliance", "connected", "offline")
    assert result.kit_manifest_digest == hashlib.sha256(kit_manifest).hexdigest()


def test_root_manifest_rejects_missing_expected_profile(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    kit_manifest = b"legacy"
    (tmp_path / MANIFEST_NAME).write_bytes(kit_manifest)
    _write_root(
        tmp_path,
        key,
        kit_manifest_digest=hashlib.sha256(kit_manifest).hexdigest(),
        profiles=["connected"],
    )

    with pytest.raises(
        OfflineKitVerificationError,
        match="expected profile is not in profiles",
    ):
        verify_root_manifest(
            tmp_path,
            release_root_pem=_public_pem(key),
            expected_profile="offline",
        )


def test_root_manifest_rejects_wrong_legacy_manifest_digest(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    (tmp_path / MANIFEST_NAME).write_bytes(b"legacy")
    _write_root(
        tmp_path,
        key,
        kit_manifest_digest="0" * 64,
        profiles=["offline"],
    )

    with pytest.raises(OfflineKitVerificationError, match="digest does not match"):
        verify_root_manifest(
            tmp_path,
            release_root_pem=_public_pem(key),
            expected_profile="offline",
        )


def test_root_manifest_rejects_invalid_signature(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    kit_manifest = b"legacy"
    (tmp_path / MANIFEST_NAME).write_bytes(kit_manifest)
    _write_root(
        tmp_path,
        key,
        kit_manifest_digest=hashlib.sha256(kit_manifest).hexdigest(),
        profiles=["offline"],
    )
    (tmp_path / ROOT_SIGNATURE_NAME).write_bytes(b"\x00" * 64)

    with pytest.raises(OfflineKitVerificationError, match="signature is invalid"):
        verify_root_manifest(
            tmp_path,
            release_root_pem=_public_pem(key),
            expected_profile="offline",
        )
