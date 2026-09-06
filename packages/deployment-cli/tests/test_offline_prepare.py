from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_oci_archive import make_archive

from fdai_deployment_cli import offline_prepare, runtime_stage
from fdai_deployment_cli.cli import main
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_bytes
from fdai_deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    build_offline_kit_manifest,
)
from fdai_deployment_cli.profile import write_profile
from fdai_deployment_cli.runtime_stage import stage_runtime_release

COMMIT = "a" * 40
SERVICES = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
PROFILE = ProvisionProfile(
    environment="dev",
    region="koreacentral",
    target_binding="e" * 64,
    connectivity="offline",
    host="managed-vm",
    transport="manual",
    access_method="internal_ssh",
    shadow_only=True,
    approval_quorum=1,
    monthly_cost_ceiling=500,
)


def _sbom(root: Path, paths: list[str]) -> bytes:
    return canonical_bytes(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "components": [
                {
                    "type": "file",
                    "name": name,
                    "hashes": [
                        {
                            "alg": "SHA-256",
                            "content": hashlib.sha256((root / name).read_bytes()).hexdigest(),
                        }
                    ],
                }
                for name in sorted(paths)
            ],
        }
    )


def _sign_kit(kit: Path, key: Ed25519PrivateKey) -> None:
    sbom = "sbom/kit.json"
    paths = [
        path.relative_to(kit).as_posix()
        for path in kit.rglob("*")
        if path.is_file()
        and path.relative_to(kit).as_posix() not in {sbom, MANIFEST_NAME, SIGNATURE_NAME}
    ]
    (kit / sbom).parent.mkdir(exist_ok=True)
    (kit / sbom).write_bytes(_sbom(kit, paths))
    manifest = build_offline_kit_manifest(
        kit,
        kit_version="0.1.0",
        cli_version="0.1.0",
        bundle_version="0.1.0",
        platform_tag="linux-x86_64",
        python_wheel="python/fdai_deployment_cli-0.1.0-py3-none-any.whl",
        deployment_bundle="deployment/bundle.tar.gz",
        terraform_binary="terraform/terraform",
        provider_mirror_prefix="terraform/providers",
        opa_binary="bin/opa",
        sbom_path=sbom,
    )
    (kit / MANIFEST_NAME).write_bytes(manifest)
    (kit / SIGNATURE_NAME).write_bytes(key.sign(manifest))


@pytest.fixture
def release(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey, bytes]:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    bundle = tmp_path / "bundle-source"
    (bundle / "infra").mkdir(parents=True)
    (bundle / "infra/main.tf").write_text("terraform {}\n", encoding="utf-8")
    (bundle / "sbom.cdx.json").write_bytes(_sbom(bundle, ["infra/main.tf"]))
    manifest = {
        "schema_version": "fdai.deployment.bundle.v1",
        "bundle_version": "0.1.0",
        "release_channel": "development",
        "min_cli_version": "0.1.0",
        "max_cli_version": None,
        "sbom_path": "sbom.cdx.json",
        "files": {
            name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
            for name in ("infra/main.tf", "sbom.cdx.json")
        },
    }
    document = canonical_bytes(manifest) + b"\n"
    (bundle / "manifest.json").write_bytes(document)
    (bundle / "manifest.json.sig").write_bytes(key.sign(document))
    kit = tmp_path / "kit"
    (kit / "deployment").mkdir(parents=True)
    with tarfile.open(kit / "deployment/bundle.tar.gz", "w:gz") as archive:
        archive.add(bundle, arcname="fdai-deployment-bundle-0.1.0")
    for name in (
        "python/fdai_deployment_cli-0.1.0-py3-none-any.whl",
        "terraform/terraform",
        "terraform/providers/example.zip",
        "bin/opa",
    ):
        path = kit / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic tooling, never executed")

    def payload(name: str, *, image: bool) -> dict[str, str]:
        fields = ("archive", "sbom", "provenance") if image else ("archive", "sbom")
        entry: dict[str, str] = {}
        for field in fields:
            relative = f"runtime/{name}/{field}.bin"
            path = kit / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"synthetic {name} {field}".encode())
            if image and field == "archive":
                fixture = make_archive(
                    path,
                    config_updates={"config": {}} if name == "clamav" else None,
                )
                entry["image_digest"] = fixture.manifest_digest
            entry[field] = relative
            entry[f"{field}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return entry

    runtime = {
        "schema_version": "fdai.runtime-release.v2",
        "source_commit": COMMIT,
        "platform_tag": "linux-x86_64",
        "deployment_bundle_sha256": hashlib.sha256(
            (kit / "deployment/bundle.tar.gz").read_bytes()
        ).hexdigest(),
        "services": {name: payload(name, image=True) for name in SERVICES},
        "sidecars": {"clamav": payload("clamav", image=True)},
        "console": payload("console", image=False),
        "deployment_support": payload("deployment-support", image=False),
    }
    (kit / "runtime/release.json").write_bytes(canonical_bytes(runtime))
    _sign_kit(kit, key)
    return kit, key, public


def _prepare(
    tmp_path: Path,
    release: tuple[Path, Ed25519PrivateKey, bytes],
    *,
    profile: ProvisionProfile = PROFILE,
    source_commit: str = COMMIT,
) -> dict[str, object]:
    kit, _key, public = release
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    return offline_prepare.prepare_offline_release(
        kit,
        work_dir=work,
        profile=profile,
        source_commit=source_commit,
        release_root_pem=public,
        bundle_public_key_pem=public,
        cli_version="0.1.0",
        platform_tag="linux-x86_64",
    )


def test_preparation_snapshots_complete_release_without_execution(
    tmp_path: Path, release, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("preparation must not run a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    result = _prepare(tmp_path, release)
    prepared = tmp_path / "work/prepared"
    assert result["state"] == "prepared"
    assert result["subscription_ready"] is False
    assert result["mutation_performed"] is False
    assert result["production_release_eligibility"] == "unverified"
    assert result["schema_version"] == "fdai.offline-preparation.v2"
    assert set(result["binding"]["image_content_digests"]) == {
        *(f"services/{name}" for name in SERVICES),
        "sidecars/clamav",
    }
    assert result["stage_order"].index("console") < result["stage_order"].index("initial-inventory")
    assert json.loads((prepared / "preparation.json").read_bytes()) == result
    assert stat.S_IMODE((prepared / "preparation.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(prepared.stat().st_mode) == 0o700
    kit = release[0]
    for path in kit.rglob("*"):
        if path.is_file() and path.name not in {MANIFEST_NAME, SIGNATURE_NAME}:
            assert (
                prepared / "artifacts" / path.relative_to(kit)
            ).read_bytes() == path.read_bytes()
    assert not list((tmp_path / "work").glob(".prepare-*"))


@pytest.mark.parametrize(
    "profile",
    [replace(PROFILE, connectivity="online"), replace(PROFILE, monthly_cost_ceiling=0)],
)
def test_preparation_requires_explicit_offline_intent(tmp_path: Path, release, profile) -> None:
    with pytest.raises(ValueError):
        _prepare(tmp_path, release, profile=profile)
    assert not (tmp_path / "work/prepared").exists()


@pytest.mark.parametrize(
    "change", ["revision", "runtime", "bundle", "signature", "toolchain-only", "mixed-bundle"]
)
def test_invalid_release_never_publishes_preparation(tmp_path: Path, release, change: str) -> None:
    kit, key, _public = release
    if change == "runtime":
        (kit / "runtime/core-control-plane/archive.bin").write_bytes(b"tampered")
    elif change == "bundle":
        (kit / "deployment/bundle.tar.gz").write_bytes(b"not a signed bundle")
        _sign_kit(kit, key)
    elif change == "signature":
        (kit / SIGNATURE_NAME).write_bytes(b"x" * 64)
    elif change == "toolchain-only":
        (kit / "runtime/release.json").unlink()
        _sign_kit(kit, key)
    elif change == "mixed-bundle":
        catalog = kit / "runtime/release.json"
        value = json.loads(catalog.read_bytes())
        value["deployment_bundle_sha256"] = "f" * 64
        catalog.write_bytes(canonical_bytes(value))
        _sign_kit(kit, key)
    with pytest.raises(ValueError):
        _prepare(tmp_path, release, source_commit="c" * 40 if change == "revision" else COMMIT)
    assert not (tmp_path / "work/prepared").exists()
    assert not list((tmp_path / "work").glob(".prepare-*"))


def test_replacement_after_verification_is_rejected(tmp_path: Path, release, monkeypatch) -> None:
    materialize = offline_prepare.materialize_verified_artifacts

    def replace_before_copy(root, verification, destination, **kwargs):
        (root / "runtime/operator-service/archive.bin").write_bytes(b"replacement")
        return materialize(root, verification, destination, **kwargs)

    monkeypatch.setattr(offline_prepare, "materialize_verified_artifacts", replace_before_copy)
    with pytest.raises(ValueError, match="changed"):
        _prepare(tmp_path, release)
    assert not (tmp_path / "work/prepared").exists()


def test_runtime_staging_copies_local_payloads_before_kit_signing(tmp_path: Path, release) -> None:
    source = release[0]
    kit = tmp_path / "unsigned-kit"
    kit.mkdir(mode=0o700)
    digest = stage_runtime_release(
        source,
        kit,
        deployment_bundle=source / "deployment/bundle.tar.gz",
        source_commit=COMMIT,
        platform_tag="linux-x86_64",
    )
    assert len(digest) == 64
    for path in (source / "runtime").rglob("*"):
        if path.is_file():
            assert (kit / path.relative_to(source)).read_bytes() == path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        stage_runtime_release(
            source,
            kit,
            deployment_bundle=source / "deployment/bundle.tar.gz",
            source_commit=COMMIT,
            platform_tag="linux-x86_64",
        )


def test_runtime_staging_refuses_a_signed_kit(tmp_path: Path, release) -> None:
    source = release[0]
    kit = tmp_path / "signed-kit"
    kit.mkdir(mode=0o700)
    (kit / MANIFEST_NAME).write_text("existing signature boundary", encoding="utf-8")
    with pytest.raises(ValueError, match="unsigned"):
        stage_runtime_release(
            source,
            kit,
            deployment_bundle=source / "deployment/bundle.tar.gz",
            source_commit=COMMIT,
            platform_tag="linux-x86_64",
        )
    assert not (kit / "runtime").exists()


def test_runtime_staging_bounds_bundle_before_copy(tmp_path: Path, release, monkeypatch) -> None:
    source = release[0]
    kit = tmp_path / "unsigned-kit"
    kit.mkdir(mode=0o700)
    monkeypatch.setattr(runtime_stage, "_MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        stage_runtime_release(
            source,
            kit,
            deployment_bundle=source / "deployment/bundle.tar.gz",
            source_commit=COMMIT,
            platform_tag="linux-x86_64",
        )
    assert not (kit / "runtime").exists()


def test_prepare_cli_uses_only_local_artifacts(
    tmp_path: Path, release, monkeypatch, capsys
) -> None:
    kit, _key, public = release
    profile = tmp_path / "profile.json"
    tmp_path.chmod(0o700)
    write_profile(profile, PROFILE)
    public_key = tmp_path / "release.pub"
    public_key.write_bytes(public)
    monkeypatch.setattr("fdai_deployment_cli.cli._runtime_platform_tag", lambda: "linux-x86_64")

    def forbidden(*args, **kwargs):
        pytest.fail("offline preparation must not inspect Azure")

    monkeypatch.setattr("fdai_deployment_cli.cli.azure_active_target_binding", forbidden)
    args = [
        "offline",
        "prepare",
        "--offline-kit",
        str(kit),
        "--profile",
        str(profile),
        "--release-root",
        str(public_key),
        "--bundle-public-key",
        str(public_key),
        "--source-commit",
        COMMIT,
        "--work-dir",
        str(tmp_path / "cli-work"),
        "--output",
        "json",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "prepared"
    assert result["subscription_ready"] is False
    assert main(args) == 3
    assert (tmp_path / "cli-work/prepared/preparation.json").exists()


@pytest.mark.parametrize("command", ["plan", "apply", "status", "guided", "resume"])
def test_offline_profile_blocks_workflow_before_any_external_check(
    tmp_path: Path, monkeypatch, capsys, command: str
) -> None:
    profile_path = tmp_path / "profile.json"
    tmp_path.chmod(0o700)
    write_profile(
        profile_path, replace(PROFILE, transport="github-actions", access_method="github_actions")
    )

    def forbidden(*args, **kwargs):
        pytest.fail("offline profile must block before auth, tool probing, or workflow access")

    for name in (
        "inspect_tools",
        "azure_cli_authenticated",
        "azure_active_target_binding",
        "dispatch_plan",
        "dispatch_apply",
        "workflow_status",
    ):
        monkeypatch.setattr(f"fdai_deployment_cli.cli.{name}", forbidden)
    common = ["--profile", str(profile_path), "--repository", "example/fdai", "--output", "json"]
    if command in {"guided", "resume"}:
        args = [
            "onboard",
            "guided",
            *common,
            "--source-commit",
            COMMIT,
            "--run-id",
            "run.offline",
            "--journal",
            str(tmp_path / "journal.jsonl"),
        ]
        if command == "resume":
            args += ["--resume-verification"]
    else:
        args = ["deploy", command, *common, "--commit-sha", COMMIT]
        args += (
            ["--request-id", "request.example"]
            if command == "status"
            else ["--run-id", "run.offline"]
        )
        if command == "apply":
            args += [
                "--plan-id",
                "plan.example",
                "--plan-digest",
                "b" * 64,
                "--plan-expires-at",
                "2099-12-31T23:59:59Z",
            ]
    assert main(args) == 3
    assert "offline_workflow_unavailable" in capsys.readouterr().err
