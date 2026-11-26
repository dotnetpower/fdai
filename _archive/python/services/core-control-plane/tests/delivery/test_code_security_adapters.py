"""Tests for the Ed25519 pack-signing adapters and the file-backed pack registry."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fdai.core.security.code_findings.result_import import PackRecord
from fdai.core.security.code_findings.signing import build_envelope, verify_envelope
from fdai.delivery.code_security_registry import FileRemediationPackRegistry
from fdai.delivery.code_security_signing import Ed25519PackSigner, Ed25519PackVerifier
from fdai.shared.providers.remediation_pack import PackRegistryError

_NOW = datetime(2026, 10, 7, tzinfo=UTC)


def write_signing_key(path: Path) -> Path:
    pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    return path


def test_signer_and_verifier_round_trip(tmp_path: Path) -> None:
    signer = Ed25519PackSigner(write_signing_key(tmp_path / "key.pem"))
    verifier = Ed25519PackVerifier([signer.public_key_pem()])
    envelope = build_envelope(b"manifest", signer)
    assert verify_envelope(envelope, b"manifest", verifier) == signer.key_id
    assert signer.key_id.startswith("ed25519:")


def test_signer_rejects_world_readable_key(tmp_path: Path) -> None:
    path = write_signing_key(tmp_path / "key.pem")
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        Ed25519PackSigner(path)


def _record(
    pack_id: str = "0123456789ab", expires: datetime = _NOW + timedelta(days=14)
) -> PackRecord:
    return PackRecord(pack_id, "f" * 64, "a" * 40, frozenset({"FDAI-SEC-0123456789ab"}), expires)


async def test_registry_records_revokes_and_lists(tmp_path: Path) -> None:
    registry = FileRemediationPackRegistry(tmp_path / "registry", clock=lambda: _NOW)
    await registry.record(_record())
    await registry.record(_record("ba9876543210", _NOW - timedelta(days=1)))
    assert await registry.get("0123456789ab") == _record()
    assert [r.pack_id for r in await registry.list_active()] == ["0123456789ab"]
    revoked = await registry.revoke("0123456789ab", "developer laptop lost")
    assert revoked.revoked is True
    assert (await registry.get("0123456789ab")).revoked is True  # type: ignore[union-attr]
    assert await registry.list_active() == []
    assert (tmp_path / "registry" / "0123456789ab.json").stat().st_mode & 0o077 == 0


async def test_registry_refuses_duplicates_unknown_and_bad_ids(tmp_path: Path) -> None:
    registry = FileRemediationPackRegistry(tmp_path)
    await registry.record(_record())
    with pytest.raises(PackRegistryError, match="already recorded"):
        await registry.record(_record())
    with pytest.raises(PackRegistryError, match="not recorded"):
        await registry.revoke("ffffffffffff", "x")
    with pytest.raises(PackRegistryError, match="12 lowercase hex"):
        await registry.get("../etc/passwd")
    assert await registry.get("aaaaaaaaaaaa") is None
