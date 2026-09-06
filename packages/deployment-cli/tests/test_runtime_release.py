from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fdai_deployment_cli import offline_kit
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.runtime_release import (
    RUNTIME_RELEASE_PATH,
    RuntimeRelease,
    RuntimeReleaseError,
    load_runtime_release,
)

COMMIT = "a" * 40
PLATFORM = "linux-x86_64"
BUNDLE_DIGEST = hashlib.sha256(b"synthetic signed deployment bundle").hexdigest()
SERVICES = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)


def _catalog(root: Path) -> dict[str, Any]:
    def record(role: str, service: bool = False) -> dict[str, str]:
        result = {}
        for kind in ("archive", "sbom", "provenance") if service else ("archive", "sbom"):
            relative = f"runtime/{role}/{kind}.bin"
            content = f"synthetic {role} {kind}".encode()
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            result[kind] = relative
            result[f"{kind}_sha256"] = hashlib.sha256(content).hexdigest()
        if service:
            result["image_digest"] = "sha256:" + "b" * 64
        return result

    return {
        "schema_version": "fdai.runtime-release.v1",
        "source_commit": COMMIT,
        "platform_tag": PLATFORM,
        "deployment_bundle_sha256": BUNDLE_DIGEST,
        "services": {role: record(role, True) for role in SERVICES},
        "console": record("console"),
        "deployment_support": record("deployment-support"),
    }


def _save(root: Path, catalog: object) -> None:
    (root / RUNTIME_RELEASE_PATH).write_bytes(canonical_bytes(catalog))


def _load(root: Path, **expected: str) -> RuntimeRelease:
    return load_runtime_release(
        root,
        expected_source_commit=expected.get("commit", COMMIT),
        expected_platform_tag=expected.get("platform", PLATFORM),
    )


@pytest.mark.parametrize("platform", [PLATFORM, "linux-aarch64"])
def test_runtime_release_validates_local_bytes_and_canonical_metadata(
    tmp_path: Path, platform: str
) -> None:
    """Opaque synthetic archives, SBOMs, and provenance need only matching file hashes."""

    catalog = _catalog(tmp_path)
    catalog["platform_tag"] = platform
    _save(tmp_path, catalog)
    result = _load(tmp_path, platform=platform)
    assert result.source_commit == COMMIT
    assert result.platform_tag == platform
    assert result.deployment_bundle_sha256 == BUNDLE_DIGEST
    assert result.digest == hashlib.sha256(canonical_bytes(catalog)).hexdigest()
    assert result.to_mapping() == catalog
    assert len(result.artifact_paths) == 19
    assert result.artifact_paths == tuple(sorted(result.artifact_paths))
    assert RUNTIME_RELEASE_PATH not in result.artifact_paths
    for path in result.artifact_paths:
        assert (tmp_path / path).read_bytes().startswith(b"synthetic ")
    detached = result.to_mapping()
    detached_services = detached["services"]
    assert isinstance(detached_services, dict)
    detached_services.clear()
    assert result.to_mapping() == catalog
    (tmp_path / RUNTIME_RELEASE_PATH).write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    assert _load(tmp_path, platform=platform).digest == result.digest
    (tmp_path / "unrelated.txt").write_bytes(b"outside the runtime subtree")
    assert _load(tmp_path, platform=platform).digest == result.digest


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("", "schema_version", "fdai.runtime-release.v2"),
        ("", "schema_version", None),
        ("", "source_commit", "a" * 39),
        ("", "source_commit", "g" * 40),
        ("", "source_commit", 1),
        ("", "platform_tag", "darwin-aarch64"),
        ("", "platform_tag", []),
        ("", "services", []),
        ("", "console", None),
        ("", "deployment_support", True),
        ("", "extra", "unexpected"),
        ("services", "extra-service", {}),
        ("services", "core-control-plane", "registry.example.com/core@sha256:" + "b" * 64),
        ("console", "image_digest", "sha256:" + "b" * 64),
        ("deployment_support", "provenance", "runtime/provenance.json"),
    ],
)
def test_runtime_release_rejects_invalid_schema(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    catalog = _catalog(tmp_path)
    (catalog[section] if section else catalog)[key] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


@pytest.mark.parametrize("section", ["", "services", "console", "deployment_support", *SERVICES])
def test_runtime_release_rejects_missing_keys(tmp_path: Path, section: str) -> None:
    catalog = _catalog(tmp_path)
    record = catalog["services"][section] if section in SERVICES else catalog.get(section, catalog)
    record.pop(next(iter(record)))
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="schema"):
        _load(tmp_path)


def test_runtime_release_rejects_extra_service_fields(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog["services"][SERVICES[0]]["registry"] = "registry.example.com"
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="schema"):
        _load(tmp_path)


@pytest.mark.parametrize("value", [None, True, [], "", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_runtime_release_rejects_invalid_deployment_bundle_digest(
    tmp_path: Path, value: object
) -> None:
    catalog = _catalog(tmp_path)
    catalog["deployment_bundle_sha256"] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="deployment bundle digest"):
        _load(tmp_path)


def test_runtime_release_requires_deployment_bundle_digest(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    del catalog["deployment_bundle_sha256"]
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="schema"):
        _load(tmp_path)


def test_runtime_release_catalog_digest_binds_deployment_bundle(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    original = _load(tmp_path)
    replacement = hashlib.sha256(b"different synthetic deployment bundle").hexdigest()
    catalog["deployment_bundle_sha256"] = replacement
    _save(tmp_path, catalog)
    changed = _load(tmp_path)
    assert changed.deployment_bundle_sha256 == replacement
    assert changed.digest != original.digest


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/runtime/a",
        "runtime",
        "other/a",
        "runtime/../a",
        "runtime/./a",
        "runtime//a",
        "runtime/a/",
        "runtime/a\\b",
        "runtime/a\nb",
        "runtime/\x00a",
        "runtime/\u00e9",
        "runtime/release.json",
        "registry.example.com/core@sha256:" + "b" * 64,
    ],
)
def test_runtime_release_rejects_unsafe_paths(tmp_path: Path, value: str) -> None:
    catalog = _catalog(tmp_path)
    catalog["console"]["archive"] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="path"):
        _load(tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "archive",
        "archive_sha256",
        "image_digest",
        "sbom",
        "sbom_sha256",
        "provenance",
        "provenance_sha256",
    ],
)
@pytest.mark.parametrize("value", [None, True, 7, [], {}])
def test_runtime_release_rejects_nonstring_fields(tmp_path: Path, key: str, value: object) -> None:
    catalog = _catalog(tmp_path)
    catalog["services"][SERVICES[0]][key] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="strings"):
        _load(tmp_path)


@pytest.mark.parametrize(
    "key", ["archive_sha256", "sbom_sha256", "provenance_sha256", "image_digest"]
)
@pytest.mark.parametrize("value", ["", "A" * 64, "g" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n"])
def test_runtime_release_rejects_invalid_hashes(tmp_path: Path, key: str, value: str) -> None:
    catalog = _catalog(tmp_path)
    catalog["services"][SERVICES[0]][key] = ("sha256:" if key == "image_digest" else "") + value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="digest"):
        _load(tmp_path)


@pytest.mark.parametrize("kind", ["archive", "sbom", "provenance"])
@pytest.mark.parametrize("failure", ["missing", "changed", "symlink", "fifo", "directory"])
def test_runtime_release_requires_real_regular_artifacts(
    tmp_path: Path, kind: str, failure: str
) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    path = tmp_path / catalog["services"][SERVICES[0]][kind]
    path.unlink()
    if failure == "changed":
        path.write_bytes(b"registry.example.com/core@sha256:" + b"b" * 64)
    elif failure == "symlink":
        path.symlink_to(tmp_path / catalog["console"]["archive"])
    elif failure == "fifo":
        os.mkfifo(path)
    elif failure == "directory":
        path.mkdir()
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


@pytest.mark.parametrize("section", ["console", "deployment_support"])
@pytest.mark.parametrize("kind", ["archive", "sbom"])
def test_runtime_release_requires_console_and_support_bytes(
    tmp_path: Path, section: str, kind: str
) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    (tmp_path / catalog[section][kind]).unlink()
    with pytest.raises(RuntimeReleaseError, match="exact file set"):
        _load(tmp_path)


def test_runtime_release_rejects_registry_metadata_without_local_bytes(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    for role in SERVICES:
        (tmp_path / catalog["services"][role]["archive"]).unlink()
    with pytest.raises(RuntimeReleaseError, match="exact file set"):
        _load(tmp_path)


@pytest.mark.parametrize("name", ["extra.bin", "offline-kit.json", "offline-kit.json.sig", "empty"])
def test_runtime_release_rejects_extra_entries(tmp_path: Path, name: str) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    extra = tmp_path / "runtime" / name
    if name == "empty":
        extra.mkdir()
    else:
        extra.write_bytes(b"extra")
    with pytest.raises(RuntimeReleaseError, match="exact file set|extra"):
        _load(tmp_path)


@pytest.mark.parametrize("location", ["root", "ancestor", "runtime", "service", "catalog"])
def test_runtime_release_rejects_symlinked_directories_and_catalog(
    tmp_path: Path, location: str
) -> None:
    root = tmp_path / "kit"
    catalog = _catalog(root)
    _save(root, catalog)
    if location in {"root", "ancestor"}:
        alias = tmp_path / "alias"
        alias.symlink_to(root if location == "root" else tmp_path, target_is_directory=True)
        root = alias if location == "root" else alias / "kit"
    else:
        relative = {
            "runtime": "runtime",
            "service": "runtime/core-control-plane",
            "catalog": RUNTIME_RELEASE_PATH,
        }[location]
        source = root / relative
        moved = tmp_path / "moved"
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=location != "catalog")
    with pytest.raises(RuntimeReleaseError):
        _load(root)


@pytest.mark.parametrize("same_record", [False, True])
def test_runtime_release_rejects_duplicate_paths(tmp_path: Path, same_record: bool) -> None:
    catalog = _catalog(tmp_path)
    catalog["console"]["archive"] = (
        catalog["console"]["sbom"] if same_record else catalog["services"][SERVICES[0]]["archive"]
    )
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="duplicated"):
        _load(tmp_path)


@pytest.mark.parametrize("nested", [False, True])
def test_runtime_release_rejects_duplicate_json_keys(tmp_path: Path, nested: bool) -> None:
    catalog = _catalog(tmp_path)
    raw = canonical_bytes(catalog)
    key = b'"schema_version":' if not nested else b'"archive":'
    raw = raw.replace(key, key + b'"ignored",' + key, 1)
    (tmp_path / RUNTIME_RELEASE_PATH).write_bytes(raw)
    with pytest.raises(RuntimeReleaseError, match="duplicate"):
        _load(tmp_path)


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b"{", b"\xff", b" " * (1024 * 1024 + 1)])
def test_runtime_release_rejects_invalid_or_oversized_json(tmp_path: Path, raw: bytes) -> None:
    _catalog(tmp_path)
    (tmp_path / RUNTIME_RELEASE_PATH).write_bytes(raw)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


def test_runtime_release_requires_catalog(tmp_path: Path) -> None:
    _catalog(tmp_path)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


@pytest.mark.parametrize("expected", [{"commit": "c" * 40}, {"platform": "linux-aarch64"}])
def test_runtime_release_checks_compatibility_before_artifact_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected: dict[str, str]
) -> None:
    _save(tmp_path, _catalog(tmp_path))

    def forbidden(*args: object, **kwargs: object) -> str:
        pytest.fail("incompatible runtime release attempted artifact hashing")

    monkeypatch.setattr(offline_kit, "_sha256_nofollow", forbidden)
    with pytest.raises(RuntimeReleaseError, match="does not match"):
        _load(tmp_path, **expected)


@pytest.mark.parametrize("limit", ["file", "total"])
def test_runtime_release_inherits_offline_kit_size_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    if limit == "file":
        size = (tmp_path / RUNTIME_RELEASE_PATH).stat().st_size
        content = b"x" * (size + 1)
        path = tmp_path / catalog["console"]["archive"]
        path.write_bytes(content)
        catalog["console"]["archive_sha256"] = hashlib.sha256(content).hexdigest()
        _save(tmp_path, catalog)
        monkeypatch.setattr(offline_kit, "_MAX_FILE_BYTES", size)
    else:
        total = sum(
            path.stat().st_size for path in (tmp_path / "runtime").rglob("*") if path.is_file()
        )
        monkeypatch.setattr(offline_kit, "_MAX_TOTAL_BYTES", total - 1)
    with pytest.raises(RuntimeReleaseError, match="size limit"):
        _load(tmp_path)
