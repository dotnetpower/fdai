"""Validate local runtime inventory and complete image content without execution.

The enclosing fdai.offline-kit.v1 files map signs runtime/release.json and its
artifacts. This module does not establish production trust, contact registries,
or install anything. Catalog loading checks file hashes; validate_runtime_images
also checks OCI content for a complete v2 inventory. Neither establishes SBOM or
provenance semantics, image attestation, or operational success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import cast

from fdai_deployment_cli import offline_kit
from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.oci_archive import (
    VerifiedOciImage,
    validate_dependency_oci_archive,
    validate_oci_archive,
)

RUNTIME_RELEASE_PATH = "runtime/release.json"
_MAX_CATALOG_BYTES = 1024 * 1024
_LEGACY_SCHEMA = "fdai.runtime-release.v1"
_SCHEMA = "fdai.runtime-release.v2"
_COMMIT = re.compile(r"[0-9a-fA-F]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PATH = re.compile(r"runtime/[A-Za-z0-9._+/-]+")
_PLATFORMS = {"linux-x86_64", "linux-aarch64"}
_SERVICES = {
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
}
_SIDECARS = {"clamav"}
_ARCHIVE_KEYS = {"archive", "archive_sha256", "sbom", "sbom_sha256"}
_SERVICE_KEYS = _ARCHIVE_KEYS | {"image_digest", "provenance", "provenance_sha256"}
_CATALOG_KEYS = {
    "schema_version",
    "source_commit",
    "platform_tag",
    "deployment_bundle_sha256",
    "services",
    "console",
    "deployment_support",
}


class RuntimeReleaseError(offline_kit.OfflineKitVerificationError):
    """Runtime release schema, compatibility, or local content is invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeRelease:
    """Immutable validated metadata; not a trust or execution authorization."""

    source_commit: str
    platform_tag: str
    deployment_bundle_sha256: str
    digest: str
    artifact_paths: tuple[str, ...]
    _catalog: bytes = field(repr=False)
    schema_version: str = _LEGACY_SCHEMA

    def to_mapping(self) -> dict[str, object]:
        """Return a detached canonical catalog mapping, without host paths or bytes."""

        return load_json_object(self._catalog, label="runtime release")


def load_runtime_release(
    root: Path, *, expected_source_commit: str, expected_platform_tag: str
) -> RuntimeRelease:
    """Check runtime/release.json and its exact local artifact set below kit root.

    Reads are bounded by the existing offline-kit per-file and total limits.
    Revision and platform must match before artifact reads. Raises
    RuntimeReleaseError with sanitized context on any invalid or unavailable input.
    No copy, extraction, execution, network access, or production trust is implied.
    Artifact payloads are opaque; matching hashes do not validate their semantics.
    Callers must compare deployment_bundle_sha256 with the separately verified
    deployment bundle archive, and snapshot and reverify bytes before use.
    """

    try:
        _require_directory(root)
        _require_directory(root / "runtime")
        raw = offline_kit._read_regular(root / RUNTIME_RELEASE_PATH, _MAX_CATALOG_BYTES)
        payload = load_json_object(raw, label="runtime release", max_bytes=_MAX_CATALOG_BYTES)
        # The shared decoder currently accepts duplicate keys; reject them at every depth.
        json.loads(raw, object_pairs_hook=_unique_object)
        schema = payload.get("schema_version")
        if not isinstance(schema, str) or schema not in (_LEGACY_SCHEMA, _SCHEMA):
            raise RuntimeReleaseError("runtime release schema version is unsupported")
        catalog = _object(payload, _CATALOG_KEYS | ({"sidecars"} if schema == _SCHEMA else set()))
        commit, platform = catalog["source_commit"], catalog["platform_tag"]
        if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
            raise RuntimeReleaseError("runtime release source commit is invalid")
        if not isinstance(platform, str) or platform not in _PLATFORMS:
            raise RuntimeReleaseError("runtime release platform is invalid")
        if commit != expected_source_commit:
            raise RuntimeReleaseError("runtime release source commit does not match")
        if platform != expected_platform_tag:
            raise RuntimeReleaseError("runtime release platform does not match")
        bundle_digest = catalog["deployment_bundle_sha256"]
        if not isinstance(bundle_digest, str) or _SHA256.fullmatch(bundle_digest) is None:
            raise RuntimeReleaseError("runtime release deployment bundle digest is invalid")
        services = _object(catalog["services"], _SERVICES)
        declared: dict[str, str] = {}
        for service in sorted(_SERVICES):
            _declare_record(services[service], service=True, declared=declared)
        if schema == _SCHEMA:
            sidecars = _object(catalog["sidecars"], _SIDECARS)
            for sidecar in sorted(_SIDECARS):
                _declare_record(sidecars[sidecar], service=True, declared=declared)
        for section in ("console", "deployment_support"):
            _declare_record(catalog[section], service=False, declared=declared)
        _verify_tree(root, {**declared, RUNTIME_RELEASE_PATH: hashlib.sha256(raw).hexdigest()})
        canonical = canonical_bytes(catalog)
        return RuntimeRelease(
            source_commit=commit,
            platform_tag=platform,
            deployment_bundle_sha256=bundle_digest,
            digest=hashlib.sha256(canonical).hexdigest(),
            artifact_paths=tuple(sorted(declared)),
            _catalog=canonical,
            schema_version=schema,
        )
    except RuntimeReleaseError:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise RuntimeReleaseError("runtime release is invalid or unavailable") from exc


def validate_runtime_images(root: Path, release: RuntimeRelease) -> dict[str, str]:
    """Validate all six v2 OCI images against a previously verified catalog snapshot.

    Inspect a private snapshot; callers own signature and release-eligibility checks.
    Images are inspected one at a time within the existing per-file limits; no layer
    extraction, process, registry call, provenance verification, or execution authority
    results from this check.
    """
    if release.schema_version != _SCHEMA:
        raise RuntimeReleaseError("complete preparation requires runtime release v2 with sidecars")
    catalog = release.to_mapping()
    digests: dict[str, str] = {}
    image: VerifiedOciImage[str] | VerifiedOciImage[None]
    for section, names in (("services", _SERVICES), ("sidecars", _SIDECARS)):
        records = _object(catalog[section], names)
        for name in sorted(names):
            record = _string_record(records[name], _SERVICE_KEYS)
            path = root / record["archive"]
            expected = {
                "expected_archive_sha256": record["archive_sha256"],
                "expected_manifest_digest": record["image_digest"],
                "expected_platform_tag": release.platform_tag,
            }
            if section == "services":
                image = validate_oci_archive(
                    path, expected_source_commit=release.source_commit, **expected
                )
            else:
                image = validate_dependency_oci_archive(path, **expected)
            digests[f"{section}/{name}"] = image.manifest.digest
            del image
    return digests


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeReleaseError("runtime release contains duplicate JSON keys")
        result[key] = value
    return result


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeReleaseError("runtime release fields do not match the schema")
    return cast(dict[str, object], value)


def _declare_record(value: object, *, service: bool, declared: dict[str, str]) -> None:
    fields = _string_record(value, _SERVICE_KEYS if service else _ARCHIVE_KEYS)
    if service and re.fullmatch(r"sha256:[0-9a-f]{64}", fields["image_digest"]) is None:
        raise RuntimeReleaseError("runtime release image digest is invalid")
    for key in ("archive", "sbom", "provenance") if service else ("archive", "sbom"):
        path, digest = fields[key], fields[f"{key}_sha256"]
        if _PATH.fullmatch(path) is None or any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            raise RuntimeReleaseError("runtime release artifact path is invalid")
        if path == RUNTIME_RELEASE_PATH or path in declared:
            raise RuntimeReleaseError(
                "runtime release artifact path is duplicated or self-referencing"
            )
        if _SHA256.fullmatch(digest) is None:
            raise RuntimeReleaseError("runtime release artifact digest is invalid")
        declared[path] = digest


def _string_record(value: object, keys: set[str]) -> dict[str, str]:
    record = _object(value, keys)
    if not all(isinstance(item, str) for item in record.values()):
        raise RuntimeReleaseError("runtime release artifact fields MUST be strings")
    return cast(dict[str, str], record)


def _require_directory(path: Path) -> None:
    """Reject directory symlinks, including supplied-root ancestors, without resolving them."""

    if ".." in path.parts:
        raise RuntimeReleaseError("runtime release root MUST NOT traverse parent directories")
    for component in (path, *path.parents):
        if not stat.S_ISDIR(component.lstat().st_mode):
            raise RuntimeReleaseError("runtime release directories MUST NOT be symlinks")


def _walk_error(error: OSError) -> None:
    raise RuntimeReleaseError("runtime release directory is unavailable") from error


def _verify_tree(root: Path, declared: dict[str, str]) -> None:
    """Enforce the runtime-only exact set using the shared no-follow digest reader."""

    directories = {
        parent.as_posix()
        for path in declared
        for parent in PurePosixPath(path).parents
        if parent.as_posix() != "."
    }
    observed: set[str] = set()
    total = 0
    for directory, children, names in os.walk(
        root / "runtime", followlinks=False, onerror=_walk_error
    ):
        base = Path(directory)
        for name in children:
            child = base / name
            if child.relative_to(root).as_posix() not in directories or not stat.S_ISDIR(
                child.lstat().st_mode
            ):
                raise RuntimeReleaseError("runtime release contains extra or symlinked directories")
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            if relative not in declared or relative in observed:
                raise RuntimeReleaseError("runtime release exact file set does not match")
            details = candidate.lstat()
            if not stat.S_ISREG(details.st_mode):
                raise RuntimeReleaseError("runtime release artifacts MUST be regular files")
            if details.st_size > offline_kit._MAX_FILE_BYTES:
                raise RuntimeReleaseError("runtime release artifact exceeds its size limit")
            total += details.st_size
            if total > offline_kit._MAX_TOTAL_BYTES:
                raise RuntimeReleaseError("runtime release exceeds its total size limit")
            if offline_kit._sha256_nofollow(candidate, expected=details) != declared[relative]:
                raise RuntimeReleaseError("runtime release artifact digest does not match")
            observed.add(relative)
    if observed != set(declared):
        raise RuntimeReleaseError("runtime release exact file set does not match")
