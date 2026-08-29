from __future__ import annotations

import base64
import hashlib
import json
import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_deployment_cli.bundle import (
    BundleVerificationError,
    _sha256,
    extract_bundle_archive,
    verify_bundle,
)
from fdai_deployment_cli.cli import (
    _create_private_work_dir,
    _absolute_work_dir,
    _require_bundle_version,
    _runtime_platform_tag,
    _safe_plan_error,
    _terraform_environment,
    _write_private_text,
    main,
)
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.doctor import ToolCheck
from fdai_deployment_cli.license import LicenseInspectionError, inspect_license
from fdai_deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    OfflineKitVerificationError,
    _sha256_nofollow,
    build_offline_kit_manifest,
    materialize_verified_artifacts,
    verify_offline_kit,
)


def _keys() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


def _kit(root: Path) -> tuple[Ed25519PrivateKey, bytes, bytes]:
    paths = (
        "python/fdai_deployment_cli-0.1.0-py3-none-any.whl",
        "deployment/bundle.tar.gz",
        "terraform/terraform",
        "terraform/providers/registry.terraform.io/hashicorp/azurerm/provider.zip",
        "bin/opa",
    )
    for value in paths:
        path = root / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode())
    sbom_path = root / "sbom/offline-kit.cdx.json"
    sbom_path.parent.mkdir(parents=True, exist_ok=True)
    sbom_path.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": [
                    {
                        "type": "file",
                        "name": value,
                        "hashes": [
                            {
                                "alg": "SHA-256",
                                "content": hashlib.sha256((root / value).read_bytes()).hexdigest(),
                            }
                        ],
                    }
                    for value in paths
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
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
        sbom_path="sbom/offline-kit.cdx.json",
    )
    private, public = _keys()
    (root / MANIFEST_NAME).write_bytes(manifest)
    (root / SIGNATURE_NAME).write_bytes(private.sign(manifest))
    return private, public, manifest


def test_offline_kit_verifies_signature_exact_files_and_compatibility(tmp_path: Path) -> None:
    private, public, manifest = _kit(tmp_path)
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
    assert result.deployment_bundle == "deployment/bundle.tar.gz"
    assert result.python_tag
    assert result.libc_tag

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

    (tmp_path / SIGNATURE_NAME).write_bytes(private.sign(manifest))
    with pytest.raises(OfflineKitVerificationError, match="Python ABI"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=public,
            cli_version="0.1.0",
            platform_tag="linux-x86_64",
            python_tag="cpython-999",
        )


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


def test_materialization_rejects_artifact_replaced_after_verification(tmp_path: Path) -> None:
    _private, public, _manifest = _kit(tmp_path)
    verification = verify_offline_kit(
        tmp_path,
        release_root_pem=public,
        cli_version="0.1.0",
        platform_tag="linux-x86_64",
    )
    (tmp_path / verification.terraform_binary).write_text("replaced", encoding="utf-8")

    with pytest.raises(OfflineKitVerificationError, match="digest changed"):
        materialize_verified_artifacts(tmp_path, verification, tmp_path / "private")


def test_materialization_snapshots_every_python_wheel(tmp_path: Path) -> None:
    _private, public, _manifest = _kit(tmp_path)
    verification = verify_offline_kit(
        tmp_path,
        release_root_pem=public,
        cli_version="0.1.0",
        platform_tag="linux-x86_64",
    )
    artifacts = materialize_verified_artifacts(tmp_path, verification, tmp_path / "private")

    assert sorted(path.name for path in artifacts.python_wheels.glob("*.whl")) == [
        "fdai_deployment_cli-0.1.0-py3-none-any.whl"
    ]


def test_offline_kit_rejects_incomplete_sbom(tmp_path: Path) -> None:
    private, public, _manifest = _kit(tmp_path)
    sbom = tmp_path / "sbom/offline-kit.cdx.json"
    sbom.write_text(
        '{"bomFormat":"CycloneDX","specVersion":"1.5","version":1,"components":[]}\n',
        encoding="utf-8",
    )
    manifest = build_offline_kit_manifest(
        tmp_path,
        kit_version="0.1.0",
        cli_version="0.1.0",
        bundle_version="0.1.0",
        platform_tag="linux-x86_64",
        python_wheel="python/fdai_deployment_cli-0.1.0-py3-none-any.whl",
        deployment_bundle="deployment/bundle.tar.gz",
        terraform_binary="terraform/terraform",
        provider_mirror_prefix="terraform/providers",
        opa_binary="bin/opa",
        sbom_path="sbom/offline-kit.cdx.json",
    )
    (tmp_path / MANIFEST_NAME).write_bytes(manifest)
    (tmp_path / SIGNATURE_NAME).write_bytes(private.sign(manifest))

    with pytest.raises(OfflineKitVerificationError, match="SBOM coverage"):
        verify_offline_kit(
            tmp_path,
            release_root_pem=public,
            cli_version="0.1.0",
            platform_tag="linux-x86_64",
        )


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


def test_bundle_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("unsafe", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(payload, arcname="../escape")

    with pytest.raises(BundleVerificationError, match="path is invalid"):
        extract_bundle_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_bundle_archive_maps_malformed_input_to_stable_error(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"not-a-tar")

    with pytest.raises(BundleVerificationError, match="archive is invalid"):
        extract_bundle_archive(archive, tmp_path / "out")


def test_bundle_archive_maps_truncated_gzip_to_stable_error(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"\x1f\x8b")

    with pytest.raises(BundleVerificationError, match="archive is invalid"):
        extract_bundle_archive(archive, tmp_path / "out")


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


def test_license_rejects_invalid_identifiers_and_unverified_bindings() -> None:
    private, public = _keys()
    now = datetime(2026, 8, 29, tzinfo=UTC)
    payload = {
        "schema_version": "fdai.license.v1",
        "license_id": "INVALID",
        "distribution_id": "example-distribution",
        "capability_ids": ["cost.metering"],
        "not_before": (now - timedelta(minutes=1)).isoformat(),
        "not_after": (now + timedelta(minutes=1)).isoformat(),
        "image_digest": "a" * 64,
        "tenant_binding": None,
    }

    def token_for(value: dict[str, object]) -> str:
        document = canonical_bytes(value)
        return ".".join(
            base64.urlsafe_b64encode(item).rstrip(b"=").decode()
            for item in (document, private.sign(document))
        )

    with pytest.raises(LicenseInspectionError, match="identifiers"):
        inspect_license(token_for(payload), public_key_pem=public, now=now)
    payload["license_id"] = "lic-test"
    with pytest.raises(LicenseInspectionError, match="expected binding"):
        inspect_license(token_for(payload), public_key_pem=public, now=now)
    with pytest.raises(LicenseInspectionError, match="does not match"):
        inspect_license(
            token_for(payload),
            public_key_pem=public,
            now=now,
            expected_image_digest="b" * 64,
        )


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


def test_local_inspection_cannot_claim_execution_host_readiness(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: object,
) -> None:
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
    capsys.readouterr()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "fdai_deployment_cli.cli.inspect_tools",
        lambda _names: (
            ToolCheck(name="az", available=True, version="test"),
            ToolCheck(name="terraform", available=True, version="test"),
            ToolCheck(name="gh", available=True, version="test"),
        ),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "fdai_deployment_cli.cli.azure_active_target_binding",
        lambda: "a" * 64,
    )

    assert main(["provision", "inspect", "--profile", str(profile), "--output", "json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "review"
    assert result["reason_codes"] == ["execution_host_identity_unverified"]


def test_manual_profile_does_not_require_github_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: object,
) -> None:
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
                "existing-host",
                "--transport",
                "manual",
                "--access-method",
                "internal_ssh",
            ]
        )
        == 0
    )
    capsys.readouterr()
    inspected: list[tuple[str, ...]] = []

    def checks(names: tuple[str, ...]) -> tuple[ToolCheck, ...]:
        inspected.append(names)
        return tuple(ToolCheck(name=name, available=True, version="test") for name in names)

    monkeypatch.setattr("fdai_deployment_cli.cli.inspect_tools", checks)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "fdai_deployment_cli.cli.azure_active_target_binding",
        lambda: "a" * 64,
    )

    assert main(["provision", "inspect", "--profile", str(profile)]) == 2
    assert inspected == [("az", "terraform")]


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


def test_plan_work_directory_and_config_reject_existing_links(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked_work = tmp_path / "work"
    linked_work.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        _create_private_work_dir(linked_work)

    private = tmp_path / "private"
    _create_private_work_dir(private)
    config_target = tmp_path / "unrelated"
    config_target.write_text("unchanged", encoding="utf-8")
    config_link = private / "offline.tfrc"
    config_link.symlink_to(config_target)
    with pytest.raises(FileExistsError):
        _write_private_text(config_link, "replacement")
    assert config_target.read_text(encoding="utf-8") == "unchanged"


def test_relative_plan_work_directory_becomes_absolute(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    assert _absolute_work_dir(Path("work")) == tmp_path / "work"
    assert _absolute_work_dir(tmp_path / "absolute") == tmp_path / "absolute"


def test_plan_rejects_bundle_version_mismatch() -> None:
    with pytest.raises(ValueError, match="versions do not match"):
        _require_bundle_version(kit_version="0.1.0", bundle_version="0.2.0")


def test_terraform_environment_rejects_ambient_plan_controls(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    config = work / "offline.tfrc"
    config.write_text("", encoding="utf-8")
    config.chmod(0o600)
    with pytest.raises(ValueError, match="control variables"):
        _terraform_environment(
            work_dir=work,
            config=config,
            source={"HOME": str(tmp_path), "TF_CLI_ARGS_plan": "-destroy"},
            subscription_id="00000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000000",
            azure_cli_path=Path("/usr/bin/true"),
        )

    azure_cli = tmp_path / "bin/az"
    azure_cli.parent.mkdir()
    azure_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    azure_cli.chmod(0o755)
    azure_config = tmp_path / "azure"
    azure_config.mkdir(mode=0o700)
    environment = _terraform_environment(
        work_dir=work,
        config=config,
        source={
            "HOME": str(tmp_path),
            "AZURE_CONFIG_DIR": str(azure_config),
            "UNRELATED_SECRET": "do-not-copy",
        },
        subscription_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000000",
        azure_cli_path=azure_cli,
    )
    assert "UNRELATED_SECRET" not in environment
    assert environment["TF_IN_AUTOMATION"] == "1"
    assert environment["TF_DATA_DIR"].endswith("terraform-data")
    assert environment["ARM_SUBSCRIPTION_ID"] == "00000000-0000-0000-0000-000000000001"
    assert environment["PATH"].split(os.pathsep)[0] == str(azure_cli.parent)
    assert environment["AZURE_CONFIG_DIR"] == str(azure_config)


def test_terraform_environment_accepts_target_bound_managed_identity(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    config = work / "offline.tfrc"
    config.write_text("", encoding="utf-8")
    config.chmod(0o600)
    environment = _terraform_environment(
        work_dir=work,
        config=config,
        source={
            "ARM_USE_MSI": "true",
            "ARM_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
            "ARM_TENANT_ID": "00000000-0000-0000-0000-000000000000",
        },
        subscription_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000000",
        azure_cli_path=None,
    )

    assert environment["ARM_USE_MSI"] == "true"
    assert environment["ARM_CLIENT_ID"] == "00000000-0000-0000-0000-000000000003"


def test_terraform_environment_rejects_linked_azure_config(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    config = work / "offline.tfrc"
    config.write_text("", encoding="utf-8")
    config.chmod(0o600)
    target = tmp_path / "azure"
    target.mkdir(mode=0o700)
    linked = tmp_path / "linked-azure"
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="private regular directory"):
        _terraform_environment(
            work_dir=work,
            config=config,
            source={"AZURE_CONFIG_DIR": str(linked)},
            subscription_id="00000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000000",
            azure_cli_path=Path("/usr/bin/true"),
        )
