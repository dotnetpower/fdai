"""Offline deployment-kit signing script tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from fdai.deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    OfflineKitVerificationError,
    verify_offline_kit,
)

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "deployment"
    / "release"
    / "build-offline-kit.py"
)
_PLATFORM = "linux-x86_64"
_VERSION = "0.1.5"
_ARTIFACTS = {
    "python/fdai-0.1.5-py3-none-any.whl": b"wheel",
    "deployment/fdai-deployment-bundle-0.1.5.tar.gz": b"bundle",
    "terraform/terraform": b"terraform",
    "terraform/providers/registry.terraform.io/hashicorp/azurerm/provider": b"provider",
    "bin/opa": b"opa",
    "sbom/offline-kit.cdx.json": b"{}",
}
_ROLES = {
    "python_wheel": "python/fdai-0.1.5-py3-none-any.whl",
    "deployment_bundle": "deployment/fdai-deployment-bundle-0.1.5.tar.gz",
    "terraform_binary": "terraform/terraform",
    "provider_mirror_prefix": "terraform/providers",
    "opa_binary": "bin/opa",
    "sbom_path": "sbom/offline-kit.cdx.json",
}


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_offline_kit", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stage(root: Path) -> None:
    for relative, content in _ARTIFACTS.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _private_key_pem(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_key_pem(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _sign(builder: ModuleType, root: Path, private_key: Ed25519PrivateKey) -> str:
    result: str = builder.sign_offline_kit(
        root,
        private_key_pem=_private_key_pem(private_key),
        release_root_pem=_public_key_pem(private_key.public_key()),
        kit_version=_VERSION,
        cli_version=_VERSION,
        bundle_version=_VERSION,
        platform_tag=_PLATFORM,
        **_ROLES,
    )
    return result


def test_signed_kit_verifies_against_the_release_root(builder: ModuleType, tmp_path: Path) -> None:
    """The release-only signer MUST produce a kit the disconnected verifier accepts."""
    _stage(tmp_path)
    private_key = Ed25519PrivateKey.generate()

    report = json.loads(_sign(builder, tmp_path, private_key))

    assert report["file_count"] == len(_ARTIFACTS)
    assert report["platform_tag"] == _PLATFORM
    verify_offline_kit(
        tmp_path,
        release_root_pem=_public_key_pem(private_key.public_key()),
        cli_version=_VERSION,
        platform_tag=_PLATFORM,
    )


def test_signing_never_writes_key_material_into_the_kit(
    builder: ModuleType, tmp_path: Path
) -> None:
    """A kit that carries the release private key would compromise every future release."""
    _stage(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    secret = _private_key_pem(private_key)

    _sign(builder, tmp_path, private_key)

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret not in path.read_bytes()


def test_tampering_after_signing_is_rejected(builder: ModuleType, tmp_path: Path) -> None:
    _stage(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    _sign(builder, tmp_path, private_key)
    (tmp_path / "bin/opa").write_bytes(b"tampered")

    with pytest.raises(OfflineKitVerificationError, match="digest mismatch"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=_public_key_pem(private_key.public_key()),
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_resigning_replaces_the_stale_signature(builder: ModuleType, tmp_path: Path) -> None:
    """A leftover signature from an earlier build MUST NOT survive a rebuild."""
    _stage(tmp_path)
    first_key = Ed25519PrivateKey.generate()
    _sign(builder, tmp_path, first_key)
    stale_signature = (tmp_path / SIGNATURE_NAME).read_bytes()
    (tmp_path / "bin/opa").write_bytes(b"opa-next")
    second_key = Ed25519PrivateKey.generate()

    _sign(builder, tmp_path, second_key)

    assert (tmp_path / SIGNATURE_NAME).read_bytes() != stale_signature
    with pytest.raises(OfflineKitVerificationError, match="signature is invalid"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=_public_key_pem(first_key.public_key()),
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_kit_is_left_unsigned_when_it_fails_its_own_verification(
    builder: ModuleType, tmp_path: Path
) -> None:
    """A rotated release root must not leave a signature nobody can check."""
    _stage(tmp_path)
    signing_key = Ed25519PrivateKey.generate()
    other_root = _public_key_pem(Ed25519PrivateKey.generate().public_key())

    with pytest.raises(builder.OfflineKitBuildError, match="left unsigned"):
        builder.sign_offline_kit(
            tmp_path,
            private_key_pem=_private_key_pem(signing_key),
            release_root_pem=other_root,
            kit_version=_VERSION,
            cli_version=_VERSION,
            bundle_version=_VERSION,
            platform_tag=_PLATFORM,
            **_ROLES,
        )

    assert not (tmp_path / MANIFEST_NAME).exists()
    assert not (tmp_path / SIGNATURE_NAME).exists()


def test_non_ed25519_signing_key_is_rejected(builder: ModuleType, tmp_path: Path) -> None:
    _stage(tmp_path)
    rsa_pem = generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    with pytest.raises(builder.OfflineKitBuildError, match="MUST be Ed25519"):
        builder.sign_offline_kit(
            tmp_path,
            private_key_pem=rsa_pem,
            release_root_pem=b"unused",
            kit_version=_VERSION,
            cli_version=_VERSION,
            bundle_version=_VERSION,
            platform_tag=_PLATFORM,
            **_ROLES,
        )
    assert not (tmp_path / MANIFEST_NAME).exists()


def test_cli_reports_failure_without_touching_the_kit(
    builder: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(_private_key_pem(Ed25519PrivateKey.generate()))
    root_path = tmp_path / "root.pem"
    root_path.write_bytes(b"not-a-key")
    kit = tmp_path / "kit"
    kit.mkdir()

    exit_code = builder.main(
        [
            "--kit",
            str(kit),
            "--private-key",
            str(key_path),
            "--release-root",
            str(root_path),
            "--kit-version",
            _VERSION,
            "--cli-version",
            _VERSION,
            "--bundle-version",
            _VERSION,
            "--platform-tag",
            _PLATFORM,
            "--python-wheel",
            _ROLES["python_wheel"],
            "--deployment-bundle",
            _ROLES["deployment_bundle"],
            "--terraform-binary",
            _ROLES["terraform_binary"],
            "--provider-mirror-prefix",
            _ROLES["provider_mirror_prefix"],
            "--opa-binary",
            _ROLES["opa_binary"],
            "--sbom-path",
            _ROLES["sbom_path"],
        ]
    )

    assert exit_code == 1
    assert "offline kit build failed" in capsys.readouterr().err
    assert not (kit / MANIFEST_NAME).exists()
