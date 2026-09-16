from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from test_oci_archive import make_archive

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.source_runtime import verify_source_runtime
from fdai_deployment_cli.source_input import SourceDeploymentInput
from fdai_deployment_cli.runtime_build import build_runtime_release
from fdai_deployment_cli.runtime_release import (
    RUNTIME_SERVICES,
    load_runtime_release,
    validate_runtime_images,
)

COMMIT = "a" * 40
PLATFORM = "linux-x86_64"


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    source = tmp_path / "artifacts"
    source.mkdir(mode=0o700)

    def image(name: str, *, dependency: bool = False) -> dict[str, str]:
        base = source / "images" / name
        base.mkdir(parents=True)
        archive = base / "image.oci.tar"
        fixture = make_archive(archive, config_updates={"config": {}} if dependency else None)
        sbom = base / "sbom.cdx.json"
        provenance = base / "provenance.jsonl"
        sbom.write_text('{"bomFormat":"CycloneDX","specVersion":"1.5"}\n', encoding="utf-8")
        provenance.write_text('{"verificationMaterial":"synthetic-test-only"}\n', encoding="utf-8")
        return {
            "archive": archive.relative_to(source).as_posix(),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "sbom": sbom.relative_to(source).as_posix(),
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
            "provenance": provenance.relative_to(source).as_posix(),
            "provenance_sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
            "image_digest": fixture.manifest_digest,
        }

    def opaque(name: str) -> dict[str, str]:
        base = source / name
        base.mkdir(parents=True)
        archive = base / "payload.tar.gz"
        sbom = base / "sbom.cdx.json"
        archive.write_bytes(f"synthetic {name} archive".encode())
        sbom.write_text('{"bomFormat":"CycloneDX","specVersion":"1.5"}\n', encoding="utf-8")
        return {
            "archive": archive.relative_to(source).as_posix(),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "sbom": sbom.relative_to(source).as_posix(),
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        }

    descriptor: dict[str, object] = {
        "schema_version": "fdai.runtime-release-build.v1",
        "source_commit": COMMIT,
        "platform_tag": PLATFORM,
        "services": {name: image(name) for name in sorted(RUNTIME_SERVICES)},
        "sidecars": {name: image(name, dependency=True) for name in ("clamav", "pgvector")},
        "console": opaque("console"),
        "deployment_support": opaque("deployment-support"),
    }
    descriptor_path = tmp_path / "runtime-build.json"
    descriptor_path.write_bytes(canonical_bytes(descriptor))
    descriptor_path.chmod(0o600)
    bundle = tmp_path / "deployment-bundle.tar.gz"
    bundle.write_bytes(b"synthetic signed deployment bundle")
    return source, descriptor_path, bundle, descriptor


def _build(tmp_path: Path) -> tuple[dict[str, object], Path, dict[str, object]]:
    source, descriptor, bundle, raw = _fixture(tmp_path)
    output = tmp_path / "release"
    return build_runtime_release(source, descriptor, bundle, output), output, raw


def test_builds_complete_v2_release_from_prebuilt_local_artifacts(tmp_path: Path) -> None:
    result, output, descriptor = _build(tmp_path)

    release = load_runtime_release(
        output,
        expected_source_commit=COMMIT,
        expected_platform_tag=PLATFORM,
    )
    images = validate_runtime_images(output, release)
    catalog = release.to_mapping()
    assert result == {
        "schema_version": "fdai.runtime-release-build-result.v1",
        "runtime_release_digest": release.digest,
        "deployment_bundle_sha256": hashlib.sha256(
            b"synthetic signed deployment bundle"
        ).hexdigest(),
        "source_commit": COMMIT,
        "platform_tag": PLATFORM,
        "artifact_count": 25,
        "image_content_digests": images,
        "azure_mutation_performed": False,
        "production_release_eligibility": "unverified",
    }
    assert catalog["schema_version"] == "fdai.runtime-release.v2"
    assert set(catalog["services"]) == RUNTIME_SERVICES
    assert set(catalog["sidecars"]) == {"clamav", "pgvector"}
    assert set(images) == {
        *(f"services/{name}" for name in RUNTIME_SERVICES),
        "sidecars/clamav",
        "sidecars/pgvector",
    }
    for section in ("services", "sidecars"):
        for record in catalog[section].values():
            assert str(record["archive"]).endswith("/image.oci.tar")
            assert str(record["sbom"]).endswith("/sbom.cdx.json")
            assert str(record["provenance"]).endswith("/provenance.jsonl")
    assert not (output / "runtime/.fdai-incomplete").exists()
    assert descriptor["services"] != catalog["services"]


def _source_runtime(tmp_path: Path) -> dict[str, object]:
    result, output, _descriptor = _build(tmp_path)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(mode=0o700)
    tree = snapshot / "tree"
    tree.mkdir(mode=0o700)
    content = b"synthetic source\n"
    (tree / "example.txt").write_bytes(content)
    (tree / "example.txt").chmod(0o600)
    records = [
        {"path": "example.txt", "mode": "100644", "sha256": hashlib.sha256(content).hexdigest()}
    ]
    manifest = {
        "schema_version": "fdai.source-snapshot.v1",
        "source": SourceDeploymentInput(
            root=tree,
            commit=COMMIT,
            tree="b" * 40,
            content_digest=canonical_digest({"files": records}),
            file_count=1,
        ).to_mapping(),
        "files": records,
    }
    (snapshot / "source-input.json").write_bytes(canonical_bytes(manifest))
    (snapshot / "source-input.json").chmod(0o600)
    return {
        "snapshot": snapshot,
        "snapshot_digest": canonical_digest(manifest),
        "runtime_root": output,
        "runtime_digest": result["runtime_release_digest"],
        "deployment_bundle": tmp_path / "deployment-bundle.tar.gz",
        "bundle_digest": result["deployment_bundle_sha256"],
        "platform_tag": PLATFORM,
    }


def test_source_runtime_content_is_bound_and_grants_no_authority(tmp_path: Path) -> None:
    args = _source_runtime(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = verify_source_runtime(**args)
    assert result["source_commit"] == COMMIT
    assert result["source_snapshot_digest"] == args["snapshot_digest"]
    assert len(result["image_content_digests"]) == 7
    for key in (
        "release_signature_verified",
        "bundle_source_verified",
        "support_contents_verified",
        "registry_published",
        "apply_authorized",
        "deployment_ready",
        "mutation_performed",
    ):
        assert result[key] is False
    digest = result.pop("receipt_digest")
    assert digest == canonical_digest(result)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    "field", ["snapshot_digest", "runtime_digest", "bundle_digest", "platform_tag"]
)
def test_source_runtime_rejects_mismatched_bindings(tmp_path: Path, field: str) -> None:
    args = _source_runtime(tmp_path)
    args[field] = "linux-aarch64" if field == "platform_tag" else "f" * 64
    with pytest.raises(ValueError):
        verify_source_runtime(**args)


@pytest.mark.parametrize("changed", ["source", "bundle", "image", "support"])
def test_source_runtime_rejects_changed_payload(tmp_path: Path, changed: str) -> None:
    args = _source_runtime(tmp_path)
    paths = {
        "source": args["snapshot"] / "tree/example.txt",
        "bundle": args["deployment_bundle"],
        "image": args["runtime_root"] / "runtime/sidecars/clamav/image.oci.tar",
        "support": args["runtime_root"] / "runtime/deployment-support/deployment-support.tar.gz",
    }
    paths[changed].write_bytes(b"changed")
    with pytest.raises(ValueError):
        verify_source_runtime(**args)


@pytest.mark.parametrize("changed", ["source", "bundle", "runtime"])
def test_source_runtime_rejects_changes_during_image_verification(tmp_path, monkeypatch, changed):
    from fdai_deployment_cli import source_runtime

    args = _source_runtime(tmp_path)
    original = source_runtime.validate_runtime_images

    def validate_then_change(root, release):
        result = original(root, release)
        paths = {
            "source": args["snapshot"] / "tree/example.txt",
            "bundle": args["deployment_bundle"],
            "runtime": args["runtime_root"] / "runtime/console/console.tar.gz",
        }
        paths[changed].write_bytes(b"changed after OCI validation")
        return result

    monkeypatch.setattr(source_runtime, "validate_runtime_images", validate_then_change)
    with pytest.raises(ValueError):
        verify_source_runtime(**args)


@pytest.mark.parametrize("invalid", [False, True])
def test_source_runtime_command_never_logs_in_or_creates_work_directory(
    tmp_path: Path, monkeypatch, capsys, invalid: bool
) -> None:
    import json

    from fdai_deployment_cli import standalone_host

    args = _source_runtime(tmp_path)
    if invalid:
        args["runtime_digest"] = "f" * 64

    def unexpected(*positional, **keywords):
        pytest.fail("content verification cannot login, install or execute")

    for name in ("_managed_identity_login", "_run", "_capture", "_acquire_checkpoint_lock"):
        monkeypatch.setattr(standalone_host, name, unexpected)
    options = {
        "snapshot": "source-snapshot",
        **{key: key.replace("_", "-") for key in args if key != "snapshot"},
    }
    command = ["--work-dir", str(tmp_path / "unused"), "verify-source-runtime"]
    for name, value in args.items():
        command.extend(["--" + options[name], str(value)])
    assert standalone_host.main(command) == (3 if invalid else 0)
    captured = capsys.readouterr()
    if invalid:
        assert not captured.out
        assert "differs from the retained digest" in captured.err
    else:
        result = json.loads(captured.out)
        assert result["state"] == "content-verified"
        assert result["deployment_ready"] is False
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("schema", "schema_version"),
        ("extra-field", "fields"),
        ("missing-service", "services"),
        ("extra-sidecar", "sidecars"),
        ("bad-commit", "source_commit"),
        ("bad-platform", "platform_tag"),
        ("bad-digest", "image digest"),
        ("traversal", "source path"),
    ],
)
def test_rejects_descriptor_that_cannot_define_one_closed_release(
    tmp_path: Path, change: str, message: str
) -> None:
    source, descriptor_path, bundle, descriptor = _fixture(tmp_path)
    if change == "schema":
        descriptor["schema_version"] = "fdai.runtime-release-build.v2"
    elif change == "extra-field":
        descriptor["extra"] = True
    elif change == "missing-service":
        descriptor["services"].pop("operator-service")
    elif change == "extra-sidecar":
        descriptor["sidecars"]["opa"] = descriptor["sidecars"]["clamav"]
    elif change == "bad-commit":
        descriptor["source_commit"] = "a" * 39
    elif change == "bad-platform":
        descriptor["platform_tag"] = "windows-x86_64"
    elif change == "bad-digest":
        descriptor["services"]["operator-service"]["image_digest"] = "sha256:" + "A" * 64
    else:
        descriptor["console"]["archive"] = "../console.tar.gz"
    descriptor_path.write_bytes(canonical_bytes(descriptor))
    descriptor_path.chmod(0o600)

    with pytest.raises(ValueError, match=message):
        build_runtime_release(source, descriptor_path, bundle, tmp_path / "release")

    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("failure", ["missing", "empty", "symlink", "fifo", "changed-image"])
def test_rejects_invalid_payload_before_publishing_release(tmp_path: Path, failure: str) -> None:
    source, descriptor_path, bundle, descriptor = _fixture(tmp_path)
    record = descriptor["services"]["core-control-plane"]
    path = source / record["archive"]
    if failure == "missing":
        path.unlink()
    elif failure == "empty":
        path.write_bytes(b"")
    elif failure == "symlink":
        path.unlink()
        path.symlink_to(source / descriptor["services"]["operator-service"]["archive"])
    elif failure == "fifo":
        path.unlink()
        os.mkfifo(path)
    else:
        path.write_bytes(b"not an OCI archive")

    with pytest.raises(ValueError):
        build_runtime_release(source, descriptor_path, bundle, tmp_path / "release")

    assert not (tmp_path / "release").exists()


def test_rejects_duplicate_descriptor_keys(tmp_path: Path) -> None:
    source, descriptor_path, bundle, _descriptor = _fixture(tmp_path)
    payload = descriptor_path.read_bytes().replace(
        b'"schema_version":',
        b'"schema_version":"duplicate","schema_version":',
        1,
    )
    descriptor_path.write_bytes(payload)
    descriptor_path.chmod(0o600)

    with pytest.raises(ValueError, match="duplicate"):
        build_runtime_release(source, descriptor_path, bundle, tmp_path / "release")


def test_private_descriptor_and_new_output_are_required(tmp_path: Path) -> None:
    source, descriptor, bundle, _raw = _fixture(tmp_path)
    descriptor.chmod(0o644)
    with pytest.raises(PermissionError, match="mode-0600"):
        build_runtime_release(source, descriptor, bundle, tmp_path / "release")

    descriptor.chmod(0o600)
    output = tmp_path / "release"
    output.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="already exists"):
        build_runtime_release(source, descriptor, bundle, output)


def test_marker_removal_failure_leaves_only_an_explicit_incomplete_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, descriptor, bundle, _raw = _fixture(tmp_path)
    output = tmp_path / "release"
    original = Path.unlink

    def fail_marker(path: Path, *args: object, **kwargs: object) -> None:
        if path.name == ".fdai-incomplete":
            raise PermissionError("synthetic marker failure")
        original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_marker)
    with pytest.raises(ValueError, match="publication is incomplete"):
        build_runtime_release(source, descriptor, bundle, output)

    assert (output / "runtime/.fdai-incomplete").is_file()
    with pytest.raises(ValueError, match="exact file set"):
        load_runtime_release(
            output,
            expected_source_commit=COMMIT,
            expected_platform_tag=PLATFORM,
        )
    with pytest.raises(ValueError, match="already exists"):
        build_runtime_release(source, descriptor, bundle, output)


def test_wrong_service_revision_and_dependency_revision_are_not_equivalent(
    tmp_path: Path,
) -> None:
    source, descriptor_path, bundle, descriptor = _fixture(tmp_path)
    service = descriptor["services"]["core-control-plane"]
    replacement = make_archive(
        source / service["archive"],
        config_updates={"config": {"Labels": {"org.opencontainers.image.revision": "b" * 40}}},
    )
    service["image_digest"] = replacement.manifest_digest
    service["archive_sha256"] = hashlib.sha256(
        (source / service["archive"]).read_bytes()
    ).hexdigest()
    descriptor_path.write_bytes(canonical_bytes(descriptor))
    descriptor_path.chmod(0o600)

    with pytest.raises(ValueError, match="revision"):
        build_runtime_release(source, descriptor_path, bundle, tmp_path / "release")
