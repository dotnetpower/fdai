"""Offline-kit acceptance drills from the release trust ceremony runbook.

`docs/runbooks/offline-trust-ceremony.md` defines the drill a disconnected host
must survive before a kit is trusted. The drills that depend only on the
manifest contract are executable today and live here; the drills that depend on
repository metadata (expiry, rollback, mixed releases) are named in
`test_metadata_drills_are_not_executable_yet` so their absence stays visible
instead of looking like coverage.

Unlike the contract tests in `test_offline_kit.py`, these stage a realistically
shaped kit - a deep provider mirror, many small wheels, and larger binaries -
and drive the full build, sign, and verify path.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    OfflineKitVerificationError,
    build_offline_kit_manifest,
    verify_offline_kit,
)

_PLATFORM = "linux-x86_64"
_VERSION = "0.1.5"
_WHEEL = "python/fdai-0.1.5-py3-none-any.whl"
_BUNDLE = "deployment/fdai-deployment-bundle-0.1.5.tar.gz"
_TERRAFORM = "terraform/terraform"
_MIRROR = "terraform/providers"
_OPA = "bin/opa"
_SBOM = "sbom/offline-kit.cdx.json"
_ROLES = {
    "python_wheel": _WHEEL,
    "deployment_bundle": _BUNDLE,
    "terraform_binary": _TERRAFORM,
    "provider_mirror_prefix": _MIRROR,
    "opa_binary": _OPA,
    "sbom_path": _SBOM,
}


def _write(root: Path, relative: str, payload: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _stage_realistic_kit(root: Path) -> None:
    """Stage a kit shaped like a real release: many files, deep mirror paths."""
    _write(root, _WHEEL, b"wheel-payload")
    _write(root, _BUNDLE, b"bundle-payload")
    _write(root, _TERRAFORM, b"terraform-binary" * 1024)
    _write(root, _OPA, b"opa-binary" * 1024)
    _write(root, _SBOM, b'{"bomFormat":"CycloneDX"}')
    for index in range(64):
        _write(root, f"python/transitive_dependency_{index:03d}-1.0.0-py3-none-any.whl", b"dep")
    for index in range(64):
        _write(
            root,
            f"{_MIRROR}/registry.terraform.io/hashicorp/azurerm/4.0.{index}/"
            "terraform-provider-azurerm_linux_amd64.zip",
            b"provider",
        )


def _sign(root: Path, private_key: Ed25519PrivateKey) -> None:
    manifest_bytes = build_offline_kit_manifest(
        root,
        kit_version=_VERSION,
        cli_version=_VERSION,
        bundle_version=_VERSION,
        platform_tag=_PLATFORM,
        **_ROLES,
    )
    (root / MANIFEST_NAME).write_bytes(manifest_bytes)
    (root / SIGNATURE_NAME).write_bytes(private_key.sign(manifest_bytes))


def _release_root(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


@pytest.fixture
def signed_kit(tmp_path: Path) -> tuple[Path, bytes]:
    private_key = Ed25519PrivateKey.generate()
    kit_root = tmp_path / "kit"
    kit_root.mkdir()
    _stage_realistic_kit(kit_root)
    _sign(kit_root, private_key)
    return kit_root, _release_root(private_key)


def _verify(
    kit: tuple[Path, bytes],
    *,
    cli_version: str = _VERSION,
    platform_tag: str = _PLATFORM,
) -> None:
    root, release_root = kit
    verify_offline_kit(
        root,
        release_root_pem=release_root,
        cli_version=cli_version,
        platform_tag=platform_tag,
    )


def test_drill_1_a_release_signed_kit_verifies(signed_kit: tuple[Path, bytes]) -> None:
    """Drill 1: a kit signed by the release root is accepted exactly as shipped."""
    _verify(signed_kit)


def test_drill_2_one_changed_byte_is_rejected(signed_kit: tuple[Path, bytes]) -> None:
    """Drill 2: rejection MUST happen before any artifact could execute."""
    root, _root_pem = signed_kit
    binary = root / _OPA
    payload = bytearray(binary.read_bytes())
    payload[0] ^= 0x01
    binary.write_bytes(bytes(payload))

    with pytest.raises(OfflineKitVerificationError, match="digest mismatch"):
        _verify(signed_kit)


def test_drill_6_cli_and_platform_mismatch_are_rejected(signed_kit: tuple[Path, bytes]) -> None:
    """Drill 6: a kit built for another CLI or platform MUST NOT be consumed."""
    with pytest.raises(OfflineKitVerificationError, match="CLI version does not match"):
        _verify(signed_kit, cli_version="0.1.4")

    with pytest.raises(OfflineKitVerificationError, match="platform does not match"):
        _verify(signed_kit, platform_tag="linux-aarch64")


def test_drill_7a_an_unlisted_file_is_rejected(signed_kit: tuple[Path, bytes]) -> None:
    root, _root_pem = signed_kit
    _write(root, "python/smuggled_payload-1.0.0-py3-none-any.whl", b"extra")

    with pytest.raises(OfflineKitVerificationError, match="file set differs"):
        _verify(signed_kit)


def test_drill_7b_a_removed_file_is_rejected(signed_kit: tuple[Path, bytes]) -> None:
    root, _root_pem = signed_kit
    (root / _SBOM).unlink()

    with pytest.raises(OfflineKitVerificationError, match="file set differs"):
        _verify(signed_kit)


def test_drill_7c_a_symlinked_artifact_is_rejected(signed_kit: tuple[Path, bytes]) -> None:
    """A symlink would let the signed digest describe content outside the kit."""
    root, _root_pem = signed_kit
    outside = root.parent / "outside-the-kit"
    outside.write_bytes(b"opa-binary" * 1024)
    binary = root / _OPA
    binary.unlink()
    binary.symlink_to(outside)

    with pytest.raises(OfflineKitVerificationError, match="symlink"):
        _verify(signed_kit)


def test_drill_8_verification_opens_no_socket(
    signed_kit: tuple[Path, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drill 8: success MUST NOT depend on any public endpoint.

    A disconnected site cannot reach a revocation responder or a metadata
    server, so verification is only trustworthy if it never tries. Any socket
    construction during verification fails this drill.
    """

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline verification MUST NOT create a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    _verify(signed_kit)


def test_metadata_drills_are_not_executable_yet(signed_kit: tuple[Path, bytes]) -> None:
    """Drills 3, 4, and 5 need repository metadata that does not exist yet.

    Expired metadata, rollback to an older version, and mixed-release metadata
    are properties of the release repository, not of the manifest contract.
    Until the trust-root ceremony packages a pinned public root, a kit carries
    only a detached signature, so those drills can neither pass nor fail here.
    This test records that boundary and asserts the strongest claim available
    today: a signature made by any other key is rejected.
    """
    root, _root_pem = signed_kit
    other_root = _release_root(Ed25519PrivateKey.generate())

    with pytest.raises(OfflineKitVerificationError, match="signature is invalid"):
        verify_offline_kit(
            root,
            release_root_pem=other_root,
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )
