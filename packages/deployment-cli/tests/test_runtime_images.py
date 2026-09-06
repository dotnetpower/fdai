from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_oci_archive import make_archive
from test_offline_prepare import COMMIT, SERVICES, _prepare, _sign_kit

from fdai_deployment_cli import offline_prepare
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.oci_archive import (
    OciArchiveError,
    validate_dependency_oci_archive,
    validate_oci_archive,
)
from fdai_deployment_cli.offline_kit import SIGNATURE_NAME
from fdai_deployment_cli.runtime_release import (
    RuntimeReleaseError,
    load_runtime_release,
    validate_runtime_images,
)
from fdai_deployment_cli.runtime_stage import stage_runtime_release

pytest_plugins = ["test_offline_prepare"]
PLATFORM = "linux-x86_64"
IMAGES = [(name, "services") for name in SERVICES] + [("clamav", "sidecars")]


def _load(root: Path):
    return load_runtime_release(root, expected_source_commit=COMMIT, expected_platform_tag=PLATFORM)


def test_v2_checks_every_image_without_claiming_dependency_source(release) -> None:
    root = release[0]
    runtime = _load(root)
    assert runtime.schema_version == "fdai.runtime-release.v2"
    assert len(runtime.artifact_paths) == 22
    catalog = runtime.to_mapping()
    checked = validate_runtime_images(root, runtime)
    assert checked == {
        f"{section}/{name}": catalog[section][name]["image_digest"] for name, section in IMAGES
    }


@pytest.mark.parametrize("labels", [{}, {"org.opencontainers.image.revision": "vendor-release"}])
def test_dependency_validation_does_not_require_an_fdai_revision(tmp_path: Path, labels) -> None:
    fixture = make_archive(
        tmp_path / "dependency.tar", config_updates={"config": {"Labels": labels}}
    )
    expected = fixture.expectations()
    expected.pop("expected_source_commit")
    image = validate_dependency_oci_archive(fixture.path, **expected)
    assert image.source_commit is None
    assert image.manifest.digest == fixture.manifest_digest
    with pytest.raises(OciArchiveError, match="revision"):
        validate_oci_archive(fixture.path, expected_source_commit=COMMIT, **expected)


@pytest.mark.parametrize(
    "defect",
    [
        "missing-sidecars",
        "missing-clamav",
        "extra-sidecar",
        "not-object",
        "missing-archive",
        "unknown-field",
        "duplicate-path",
        "bad-digest",
        "registry-only",
        "traversal",
        "symlink",
    ],
)
def test_sidecars_use_the_same_closed_catalog_boundary(release, defect: str) -> None:
    root, _, _ = release
    catalog_path = root / "runtime/release.json"
    catalog = json.loads(catalog_path.read_bytes())
    sidecars = catalog["sidecars"]
    clamav = sidecars["clamav"]
    if defect == "missing-sidecars":
        del catalog["sidecars"]
    elif defect == "missing-clamav":
        del sidecars[defect.removeprefix("missing-")]
    elif defect == "extra-sidecar":
        sidecars["opa"] = clamav
    elif defect == "not-object":
        catalog["sidecars"] = []
    elif defect == "missing-archive":
        del clamav["archive"]
    elif defect == "unknown-field":
        clamav["source_commit"] = COMMIT
    elif defect == "duplicate-path":
        clamav["archive"] = catalog["services"][SERVICES[0]]["archive"]
    elif defect == "bad-digest":
        clamav["image_digest"] = "sha256:" + "A" * 64
    elif defect == "registry-only":
        clamav["archive"] = "registry.example.com/clamav@sha256:" + "a" * 64
    elif defect == "traversal":
        clamav["archive"] = "runtime/../archive"
    else:
        path = root / clamav["archive"]
        path.unlink()
        path.symlink_to(root / catalog["services"][SERVICES[0]]["archive"])
    catalog_path.write_bytes(canonical_bytes(catalog))
    with pytest.raises(RuntimeReleaseError):
        _load(root)


@pytest.mark.parametrize(("name", "section"), IMAGES)
@pytest.mark.parametrize("defect", ["opaque-bytes", "manifest-mismatch", "wrong-platform"])
@pytest.mark.parametrize("operation", ["prepare", "stage"])
def test_signed_bad_image_never_publishes_a_snapshot(
    tmp_path: Path, release, name: str, section: str, defect: str, operation: str
) -> None:
    root, key, _ = release
    catalog_path = root / "runtime/release.json"
    catalog = json.loads(catalog_path.read_bytes())
    record = catalog[section][name]
    path = root / record["archive"]
    if defect == "opaque-bytes":
        path.write_bytes(b"hashed and signed, but not an OCI image")
    elif defect == "manifest-mismatch":
        record["image_digest"] = "sha256:" + "f" * 64
    else:
        fixture = make_archive(path, config_updates={"architecture": "arm64"})
        record["image_digest"] = fixture.manifest_digest
    record["archive_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    catalog_path.write_bytes(canonical_bytes(catalog))
    _sign_kit(root, key)
    _load(root)  # Valid catalog hashes are not sufficient for image content.
    with pytest.raises(OciArchiveError):
        if operation == "prepare":
            _prepare(tmp_path, release)
        else:
            kit = tmp_path / "work"
            kit.mkdir(mode=0o700)
            stage_runtime_release(
                root,
                kit,
                deployment_bundle=root / "deployment/bundle.tar.gz",
                source_commit=COMMIT,
                platform_tag=PLATFORM,
            )
    assert list((tmp_path / "work").iterdir()) == []


def test_service_revision_is_checked_even_when_all_payload_hashes_match(tmp_path: Path, release):
    root, key, _ = release
    catalog_path = root / "runtime/release.json"
    catalog = json.loads(catalog_path.read_bytes())
    record = catalog["services"][SERVICES[0]]
    path = root / record["archive"]
    fixture = make_archive(path, config_updates={"config": {}})
    record["image_digest"] = fixture.manifest_digest
    record["archive_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    catalog_path.write_bytes(canonical_bytes(catalog))
    _sign_kit(root, key)
    with pytest.raises(OciArchiveError, match="revision"):
        _prepare(tmp_path, release)
    assert list((tmp_path / "work").iterdir()) == []


def test_legacy_catalog_remains_stageable_but_not_a_complete_preparation(tmp_path: Path, release):
    root, key, _ = release
    catalog_path = root / "runtime/release.json"
    catalog = json.loads(catalog_path.read_bytes())
    for record in catalog.pop("sidecars").values():
        for field in ("archive", "sbom", "provenance"):
            (root / record[field]).unlink()
        (root / record["archive"]).parent.rmdir()
    catalog["schema_version"] = "fdai.runtime-release.v1"
    catalog_path.write_bytes(canonical_bytes(catalog))
    _sign_kit(root, key)
    assert _load(root).schema_version == "fdai.runtime-release.v1"
    destination = tmp_path / "legacy-stage"
    destination.mkdir(mode=0o700)
    stage_runtime_release(
        root,
        destination,
        deployment_bundle=root / "deployment/bundle.tar.gz",
        source_commit=COMMIT,
        platform_tag=PLATFORM,
    )
    assert (destination / "runtime/release.json").exists()
    with pytest.raises(RuntimeReleaseError, match="v2 with sidecars"):
        _prepare(tmp_path, release)
    assert list((tmp_path / "work").iterdir()) == []


def test_bad_kit_signature_prevents_image_inspection(tmp_path: Path, release, monkeypatch):
    root, _, _ = release
    (root / SIGNATURE_NAME).write_bytes(b"x" * 64)

    def forbidden(*args, **kwargs):
        pytest.fail("untrusted image must not reach OCI parsing")

    monkeypatch.setattr(offline_prepare, "validate_runtime_images", forbidden)
    with pytest.raises(ValueError):
        _prepare(tmp_path, release)
    assert list((tmp_path / "work").iterdir()) == []
