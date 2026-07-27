"""Tests for signed offline deployment-kit verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.deployment_cli import offline_kit
from fdai.deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    OfflineKitManifest,
    OfflineKitVerificationError,
    _file_digest,
    build_offline_kit_manifest,
    verify_offline_kit,
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


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _write_kit(root: Path) -> tuple[Ed25519PrivateKey, bytes]:
    for relative, content in _ARTIFACTS.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest = {
        "schema_version": "fdai.deployment.offline-kit.v1",
        "kit_version": _VERSION,
        "cli_version": _VERSION,
        "bundle_version": _VERSION,
        "platform_tag": _PLATFORM,
        "python_wheel": "python/fdai-0.1.5-py3-none-any.whl",
        "deployment_bundle": "deployment/fdai-deployment-bundle-0.1.5.tar.gz",
        "terraform_binary": "terraform/terraform",
        "provider_mirror_prefix": "terraform/providers",
        "opa_binary": "bin/opa",
        "sbom_path": "sbom/offline-kit.cdx.json",
        "files": {
            path: hashlib.sha256(content).hexdigest()
            for path, content in sorted(_ARTIFACTS.items())
        },
    }
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    private_key = Ed25519PrivateKey.generate()
    (root / "offline-kit.json").write_bytes(manifest_bytes)
    (root / "offline-kit.json.sig").write_bytes(private_key.sign(manifest_bytes))
    return private_key, _public_key(private_key)


def test_verifies_exact_signed_offline_kit(tmp_path: Path) -> None:
    _private_key, release_root = _write_kit(tmp_path)

    result = verify_offline_kit(
        tmp_path,
        release_root_pem=release_root,
        cli_version=_VERSION,
        platform_tag=_PLATFORM,
    )

    assert result.kit_version == _VERSION
    assert result.bundle_version == _VERSION
    assert result.file_count == len(_ARTIFACTS)
    assert json.loads(result.to_json())["schema_version"] == (
        "fdai.deployment-cli.offline-kit-verification.v1"
    )


def test_rejects_tampered_artifact(tmp_path: Path) -> None:
    _private_key, release_root = _write_kit(tmp_path)
    (tmp_path / "bin/opa").write_bytes(b"tampered")

    with pytest.raises(OfflineKitVerificationError, match="digest mismatch"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=release_root,
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_rejects_wrong_release_root(tmp_path: Path) -> None:
    _private_key, _release_root = _write_kit(tmp_path)
    wrong_root = _public_key(Ed25519PrivateKey.generate())

    with pytest.raises(OfflineKitVerificationError, match="signature is invalid"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=wrong_root,
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_rejects_extra_file(tmp_path: Path) -> None:
    _private_key, release_root = _write_kit(tmp_path)
    (tmp_path / "unexpected.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(OfflineKitVerificationError, match="file set differs"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=release_root,
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_rejects_symlink(tmp_path: Path) -> None:
    _private_key, release_root = _write_kit(tmp_path)
    (tmp_path / "link").symlink_to(tmp_path / "bin/opa")

    with pytest.raises(OfflineKitVerificationError, match="MUST NOT be a symlink"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=release_root,
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_digest_helper_never_follows_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"trusted")
    link = tmp_path / "artifact"
    link.symlink_to(target)

    with pytest.raises(OfflineKitVerificationError, match="regular file"):
        _file_digest(link)


def test_rejects_symlinked_manifest(tmp_path: Path) -> None:
    _private_key, release_root = _write_kit(tmp_path)
    manifest_path = tmp_path / "offline-kit.json"
    real_manifest = tmp_path / "real-manifest.json"
    real_manifest.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(real_manifest)

    with pytest.raises(OfflineKitVerificationError, match="metadata MUST be regular files"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=release_root,
            cli_version=_VERSION,
            platform_tag=_PLATFORM,
        )


def test_rejects_cli_version_mismatch(tmp_path: Path) -> None:
    _private_key, release_root = _write_kit(tmp_path)

    with pytest.raises(OfflineKitVerificationError, match="CLI version does not match"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=release_root,
            cli_version="0.1.4",
            platform_tag=_PLATFORM,
        )


def test_manifest_requires_provider_mirror_artifact() -> None:
    files = {
        path: hashlib.sha256(content).hexdigest()
        for path, content in _ARTIFACTS.items()
        if not path.startswith("terraform/providers/")
    }

    with pytest.raises(ValueError, match="provider mirror prefix"):
        OfflineKitManifest(
            kit_version=_VERSION,
            cli_version=_VERSION,
            bundle_version=_VERSION,
            platform_tag=_PLATFORM,
            python_wheel="python/fdai-0.1.5-py3-none-any.whl",
            deployment_bundle="deployment/fdai-deployment-bundle-0.1.5.tar.gz",
            terraform_binary="terraform/terraform",
            provider_mirror_prefix="terraform/providers",
            opa_binary="bin/opa",
            sbom_path="sbom/offline-kit.cdx.json",
            files=files,
        )


def _stage(root: Path) -> None:
    for relative, content in _ARTIFACTS.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _build(root: Path, **overrides: str) -> bytes:
    arguments: dict[str, str] = {
        "kit_version": _VERSION,
        "cli_version": _VERSION,
        "bundle_version": _VERSION,
        "platform_tag": _PLATFORM,
        "python_wheel": "python/fdai-0.1.5-py3-none-any.whl",
        "deployment_bundle": "deployment/fdai-deployment-bundle-0.1.5.tar.gz",
        "terraform_binary": "terraform/terraform",
        "provider_mirror_prefix": "terraform/providers",
        "opa_binary": "bin/opa",
        "sbom_path": "sbom/offline-kit.cdx.json",
    }
    arguments.update(overrides)
    return build_offline_kit_manifest(root, **arguments)


def test_built_manifest_verifies_after_signing(tmp_path: Path) -> None:
    """The builder and the verifier MUST agree on one staged tree."""
    _stage(tmp_path)
    manifest_bytes = _build(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    (tmp_path / MANIFEST_NAME).write_bytes(manifest_bytes)
    (tmp_path / SIGNATURE_NAME).write_bytes(private_key.sign(manifest_bytes))

    result = verify_offline_kit(
        tmp_path,
        release_root_pem=_public_key(private_key),
        cli_version=_VERSION,
        platform_tag=_PLATFORM,
    )

    assert result.file_count == len(_ARTIFACTS)
    assert result.manifest_digest == hashlib.sha256(manifest_bytes).hexdigest()


def test_build_is_byte_deterministic(tmp_path: Path) -> None:
    """Two builds of identical content MUST produce one signable byte string."""
    _stage(tmp_path)

    assert _build(tmp_path) == _build(tmp_path)


def test_build_ignores_stale_metadata_but_covers_every_artifact(tmp_path: Path) -> None:
    """A rebuild over a previously signed kit MUST NOT attest to its own metadata."""
    _stage(tmp_path)
    (tmp_path / MANIFEST_NAME).write_bytes(b"stale")
    (tmp_path / SIGNATURE_NAME).write_bytes(b"stale")

    manifest = json.loads(_build(tmp_path))

    assert set(manifest["files"]) == set(_ARTIFACTS)


def test_build_rejects_symlinked_artifact(tmp_path: Path) -> None:
    """A symlink could redirect the signed digest to content outside the kit."""
    _stage(tmp_path)
    (tmp_path / "link").symlink_to(tmp_path / "bin/opa")

    with pytest.raises(OfflineKitVerificationError, match="MUST NOT be a symlink"):
        _build(tmp_path)


def test_build_rejects_empty_stage(tmp_path: Path) -> None:
    with pytest.raises(OfflineKitVerificationError, match="stages no artifact"):
        _build(tmp_path)


def test_build_rejects_unstaged_required_artifact(tmp_path: Path) -> None:
    """A declared role that is absent from the stage MUST fail before signing."""
    _stage(tmp_path)
    (tmp_path / "bin/opa").unlink()

    with pytest.raises(ValueError, match="opa"):
        _build(tmp_path)


def test_build_rejects_a_manifest_the_verifier_could_not_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest over the verifier's size bound would sign an unverifiable kit.

    Verification reads the manifest before it can check anything, so an
    oversized manifest is rejected at the disconnected site - after the kit has
    already been signed and shipped. The builder MUST fail first.
    """
    _stage(tmp_path)
    monkeypatch.setattr(offline_kit, "_MAX_MANIFEST_BYTES", 64)

    with pytest.raises(OfflineKitVerificationError, match="manifest exceeds the size limit"):
        _build(tmp_path)


def test_build_rejects_file_count_over_limit(tmp_path: Path) -> None:
    _stage(tmp_path)

    with pytest.raises(OfflineKitVerificationError, match="file-count limit"):
        build_offline_kit_manifest(
            tmp_path,
            kit_version=_VERSION,
            cli_version=_VERSION,
            bundle_version=_VERSION,
            platform_tag=_PLATFORM,
            python_wheel="python/fdai-0.1.5-py3-none-any.whl",
            deployment_bundle="deployment/fdai-deployment-bundle-0.1.5.tar.gz",
            terraform_binary="terraform/terraform",
            provider_mirror_prefix="terraform/providers",
            opa_binary="bin/opa",
            sbom_path="sbom/offline-kit.cdx.json",
            max_files=2,
        )
