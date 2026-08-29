from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_deployment_cli.bundle import BundleVerificationError, _sha256, verify_bundle
from fdai_deployment_cli.cli import _runtime_platform_tag, _safe_plan_error, main
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.license import LicenseInspectionError, inspect_license
from fdai_deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    OfflineKitVerificationError,
    _sha256_nofollow,
    build_offline_kit_manifest,
    verify_offline_kit,
)


def _keys() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


def _kit(root: Path) -> tuple[bytes, bytes]:
    paths = (
        "python/fdai_deployment_cli-0.1.0-py3-none-any.whl",
        "deployment/bundle.tar.gz",
        "terraform/terraform",
        "terraform/providers/registry.terraform.io/hashicorp/azurerm/provider.zip",
        "bin/opa",
        "sbom/offline-kit.cdx.json",
    )
    for value in paths:
        path = root / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode())
    manifest = build_offline_kit_manifest(
        root,
        kit_version="0.1.0",
        cli_version="0.1.0",
        bundle_version="0.1.0",
        platform_tag="linux-x86_64",
        python_wheel=paths[0],
        deployment_bundle=paths[1],
        terraform_binary=paths[2],
        provider_mirror_prefix="terraform/providers",
        opa_binary=paths[4],
        sbom_path=paths[5],
    )
    private, public = _keys()
    (root / MANIFEST_NAME).write_bytes(manifest)
    (root / SIGNATURE_NAME).write_bytes(private.sign(manifest))
    return public, manifest


def test_offline_kit_verifies_signature_exact_files_and_compatibility(tmp_path: Path) -> None:
    public, manifest = _kit(tmp_path)
    result = verify_offline_kit(
        tmp_path,
        release_root_pem=public,
        cli_version="0.1.0",
        platform_tag="linux-x86_64",
    )
    assert result.file_count == 6
    assert result.manifest_digest
    assert result.terraform_binary == "terraform/terraform"
    assert result.provider_mirror_prefix == "terraform/providers"

    (tmp_path / "extra").write_text("extra", encoding="utf-8")
    with pytest.raises(OfflineKitVerificationError, match="exact file set"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=public,
            cli_version="0.1.0",
            platform_tag="linux-x86_64",
        )
    (tmp_path / "extra").unlink()
    (tmp_path / SIGNATURE_NAME).write_bytes(b"x" * 64)
    with pytest.raises(OfflineKitVerificationError, match="signature"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=public,
            cli_version="0.1.0",
            platform_tag="linux-x86_64",
        )
    assert manifest


def test_offline_kit_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("value", encoding="utf-8")
    (tmp_path / "linked").symlink_to(target)
    with pytest.raises(OfflineKitVerificationError, match="symlinks"):
        build_offline_kit_manifest(
            tmp_path,
            kit_version="0.1.0",
            cli_version="0.1.0",
            bundle_version="0.1.0",
            platform_tag="linux-x86_64",
            python_wheel="linked",
            deployment_bundle="linked",
            terraform_binary="linked",
            provider_mirror_prefix="linked",
            opa_binary="linked",
            sbom_path="linked",
        )


def test_offline_hash_rejects_replaced_file_identity(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    observed = tmp_path / "observed"
    expected.write_bytes(b"same")
    observed.write_bytes(b"same")

    with pytest.raises(OfflineKitVerificationError, match="changed during verification"):
        _sha256_nofollow(observed, expected=expected.stat())


def test_bundle_verification_rejects_tampering(tmp_path: Path) -> None:
    private, public = _keys()
    payload = tmp_path / "infra/main.tf"
    payload.parent.mkdir()
    payload.write_text("terraform {}", encoding="utf-8")
    payload_digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    sbom = tmp_path / "sbom.cdx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": [
                    {
                        "type": "file",
                        "name": "infra/main.tf",
                        "hashes": [{"alg": "SHA-256", "content": payload_digest}],
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "fdai.deployment.bundle.v1",
        "bundle_version": "0.1.0",
        "release_channel": "development",
        "min_cli_version": "0.1.0",
        "max_cli_version": None,
        "sbom_path": "sbom.cdx.json",
        "files": {
            "infra/main.tf": payload_digest,
            "sbom.cdx.json": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        },
    }
    document = canonical_bytes(manifest) + b"\n"
    (tmp_path / "manifest.json").write_bytes(document)
    (tmp_path / "manifest.json.sig").write_bytes(private.sign(document))
    assert verify_bundle(tmp_path, public_key_pem=public).file_count == 2
    payload.write_text("changed", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="exact file set"):
        verify_bundle(tmp_path, public_key_pem=public)


def test_bundle_hash_rejects_replaced_file_identity(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    observed = tmp_path / "observed"
    expected.write_bytes(b"same")
    observed.write_bytes(b"same")

    with pytest.raises(BundleVerificationError, match="changed during verification"):
        _sha256(observed, expected=expected.stat())


def test_bundle_hash_rejects_fifo_before_open(tmp_path: Path) -> None:
    fifo = tmp_path / "payload"
    os.mkfifo(fifo)

    with pytest.raises(BundleVerificationError, match="regular files"):
        _sha256(fifo, expected=fifo.stat())


def test_bundle_rejects_incompatible_cli_version(tmp_path: Path) -> None:
    private, public = _keys()
    payload = tmp_path / "infra/main.tf"
    payload.parent.mkdir()
    payload.write_text("terraform {}", encoding="utf-8")
    payload_digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    sbom = tmp_path / "sbom.cdx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": [
                    {
                        "type": "file",
                        "name": "infra/main.tf",
                        "hashes": [{"alg": "SHA-256", "content": payload_digest}],
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "fdai.deployment.bundle.v1",
        "bundle_version": "0.1.0",
        "release_channel": "development",
        "min_cli_version": "0.2.0",
        "max_cli_version": None,
        "sbom_path": "sbom.cdx.json",
        "files": {
            "infra/main.tf": payload_digest,
            "sbom.cdx.json": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        },
    }
    document = canonical_bytes(manifest) + b"\n"
    (tmp_path / "manifest.json").write_bytes(document)
    (tmp_path / "manifest.json.sig").write_bytes(private.sign(document))

    with pytest.raises(BundleVerificationError, match="incompatible"):
        verify_bundle(tmp_path, public_key_pem=public, cli_version="0.1.0")


def test_bundle_rejects_incomplete_sbom(tmp_path: Path) -> None:
    private, public = _keys()
    payload = tmp_path / "infra/main.tf"
    payload.parent.mkdir()
    payload.write_text("terraform {}", encoding="utf-8")
    sbom = tmp_path / "sbom.cdx.json"
    sbom.write_text(
        '{"bomFormat":"CycloneDX","specVersion":"1.5","version":1,"components":[]}\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "fdai.deployment.bundle.v1",
        "bundle_version": "0.1.0",
        "release_channel": "development",
        "min_cli_version": "0.1.0",
        "max_cli_version": None,
        "sbom_path": "sbom.cdx.json",
        "files": {
            "infra/main.tf": hashlib.sha256(payload.read_bytes()).hexdigest(),
            "sbom.cdx.json": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        },
    }
    document = canonical_bytes(manifest) + b"\n"
    (tmp_path / "manifest.json").write_bytes(document)
    (tmp_path / "manifest.json.sig").write_bytes(private.sign(document))

    with pytest.raises(BundleVerificationError, match="SBOM coverage"):
        verify_bundle(tmp_path, public_key_pem=public)


def test_license_inspection_verifies_signature_and_time() -> None:
    private, public = _keys()
    now = datetime(2026, 8, 29, tzinfo=UTC)
    payload = {
        "schema_version": "fdai.license.v1",
        "license_id": "lic-test",
        "distribution_id": "example-distribution",
        "capability_ids": ["cost.metering"],
        "not_before": (now - timedelta(minutes=1)).isoformat(),
        "not_after": (now + timedelta(minutes=1)).isoformat(),
        "image_digest": None,
        "tenant_binding": None,
    }
    document = canonical_bytes(payload)
    token = ".".join(
        base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        for value in (document, private.sign(document))
    )
    assert inspect_license(token, public_key_pem=public, now=now).active
    with pytest.raises(LicenseInspectionError, match="not active"):
        inspect_license(token, public_key_pem=public, now=now + timedelta(days=1))


def test_license_rejects_noncanonical_base64_and_duplicate_capabilities() -> None:
    private, public = _keys()
    now = datetime(2026, 8, 29, tzinfo=UTC)
    payload = {
        "schema_version": "fdai.license.v1",
        "license_id": "lic-test",
        "distribution_id": "example-distribution",
        "capability_ids": ["cost.metering", "cost.metering"],
        "not_before": (now - timedelta(minutes=1)).isoformat(),
        "not_after": (now + timedelta(minutes=1)).isoformat(),
        "image_digest": None,
        "tenant_binding": None,
    }
    document = canonical_bytes(payload)
    token = ".".join(
        base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        for value in (document, private.sign(document))
    )
    with pytest.raises(LicenseInspectionError, match="unique and sorted"):
        inspect_license(token, public_key_pem=public, now=now)
    with pytest.raises(LicenseInspectionError, match="canonical base64url"):
        inspect_license(f"{token}=x", public_key_pem=public, now=now)


def test_cli_version_and_private_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["version", "--output", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.1.0"
    profile = tmp_path / "private" / "profile.json"
    assert (
        main(
            [
                "provision",
                "init",
                "--profile",
                str(profile),
                "--environment",
                "dev",
                "--region",
                "koreacentral",
                "--target-binding",
                "a" * 64,
                "--connectivity",
                "online",
                "--host",
                "managed-vm",
                "--transport",
                "github-actions",
                "--access-method",
                "github_actions",
                "--output",
                "json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["mutation_performed"] is False


def test_profile_init_requires_digest_bound_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "provision",
            "init",
            "--profile",
            str(tmp_path / "profile.json"),
            "--environment",
            "dev",
            "--region",
            "koreacentral",
            "--target-binding",
            "raw-subscription-id",
            "--connectivity",
            "online",
            "--host",
            "managed-vm",
            "--transport",
            "github-actions",
            "--access-method",
            "github_actions",
        ]
    )

    assert result == 3
    assert "target_binding MUST be a lowercase SHA-256" in capsys.readouterr().err


def test_terraform_failure_is_redacted_to_stable_reason() -> None:
    secret_shaped = "token=super-secret resource=/subscriptions/example"
    assert _safe_plan_error(secret_shaped) == (
        "terraform plan failed after offline provider initialization"
    )
    assert "super-secret" not in _safe_plan_error(secret_shaped)
    assert "No value for required variable" in _safe_plan_error(
        "Error: No value for required variable\nvariable subscription"
    )


def test_runtime_platform_is_not_caller_controlled(monkeypatch: object) -> None:
    monkeypatch.setattr("fdai_deployment_cli.cli.sys.platform", "linux")  # type: ignore[attr-defined]
    monkeypatch.setattr("fdai_deployment_cli.cli.platform.machine", lambda: "AMD64")  # type: ignore[attr-defined]
    assert _runtime_platform_tag() == "linux-x86_64"
