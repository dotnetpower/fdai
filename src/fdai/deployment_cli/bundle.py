"""Verify signed deployment bundles before any Terraform command runs.

Everything here runs on input that has not been trusted yet, so the reads are
bounded before the signature is checked rather than after. The same rules apply
as in :mod:`fdai.deployment_cli.offline_kit`; the two verifiers guard the same
handover and a gap in either one is a gap in both.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import BaseModel, ConfigDict, Field, ValidationError

BUNDLE_SCHEMA: Final = "fdai.deployment.bundle.v1"
BUNDLE_VERIFICATION_SCHEMA: Final = "fdai.deployment-cli.bundle-verification.v1"
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_MANIFEST_BYTES: Final = 4 * 1024 * 1024
_MAX_SIGNATURE_BYTES: Final = 4 * 1024
_METADATA_NAMES: Final = frozenset({"manifest.json", "manifest.json.sig"})


class ReleaseChannel(StrEnum):
    STABLE = "stable"
    BETA = "beta"
    DEVELOPMENT = "development"


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeploymentBundleManifest(_ManifestModel):
    schema_version: Literal["fdai.deployment.bundle.v1"] = BUNDLE_SCHEMA
    bundle_version: str
    release_channel: ReleaseChannel
    min_cli_version: str
    max_cli_version: str | None = None
    sbom_path: str
    files: dict[str, str] = Field(min_length=1)

    def model_post_init(self, __context: object) -> None:
        _version_tuple(self.bundle_version)
        _version_tuple(self.min_cli_version)
        if self.max_cli_version is not None:
            _version_tuple(self.max_cli_version)
        for path, digest in self.files.items():
            _validate_relative_path(path)
            if _DIGEST.fullmatch(digest) is None:
                raise ValueError(f"bundle digest for {path!r} is invalid")
        if self.sbom_path not in self.files or not self.sbom_path.endswith(".json"):
            raise ValueError("bundle SBOM MUST be a listed JSON file")


@dataclass(frozen=True, slots=True)
class BundleVerification:
    bundle_version: str
    release_channel: ReleaseChannel
    manifest_digest: str
    file_count: int
    total_bytes: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "bundle_version": self.bundle_version,
                "file_count": self.file_count,
                "manifest_digest": self.manifest_digest,
                "release_channel": self.release_channel.value,
                "schema_version": BUNDLE_VERIFICATION_SCHEMA,
                "total_bytes": self.total_bytes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class BundleVerificationError(ValueError):
    """Deployment bundle verification failed before execution."""


def verify_deployment_bundle(
    root: Path,
    *,
    public_key_pem: bytes,
    cli_version: str,
    max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
) -> BundleVerification:
    """Verify one unpacked bundle directory without following symlinks."""
    if max_total_bytes < 1:
        raise ValueError("bundle size cap MUST be positive")
    _version_tuple(cli_version)
    manifest_path = root / "manifest.json"
    signature_path = root / "manifest.json.sig"
    if root.is_symlink() or not root.is_dir():
        raise BundleVerificationError("bundle root MUST be a regular directory")
    if any(path.is_symlink() or not path.is_file() for path in (manifest_path, signature_path)):
        raise BundleVerificationError("bundle metadata MUST be regular files")
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise BundleVerificationError("bundle manifest exceeds the size limit")
        if signature_path.stat().st_size > _MAX_SIGNATURE_BYTES:
            raise BundleVerificationError("bundle signature exceeds the size limit")
        manifest_bytes = manifest_path.read_bytes()
        signature = signature_path.read_bytes()
    except OSError as exc:
        raise BundleVerificationError("bundle manifest or signature is missing") from exc
    _verify_signature(public_key_pem, manifest_bytes, signature)
    try:
        manifest = DeploymentBundleManifest.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise BundleVerificationError("bundle manifest is invalid") from exc
    _validate_compatibility(manifest, cli_version)

    listed = set(manifest.files)
    actual: set[str] = set()
    total_bytes = 0

    def _unreadable(error: OSError) -> None:
        raise BundleVerificationError(f"bundle tree could not be read: {error}")

    for directory, subdirectories, names in os.walk(root, onerror=_unreadable, followlinks=False):
        base = Path(directory)
        for name in subdirectories:
            entry = base / name
            if entry.is_symlink():
                relative = entry.relative_to(root).as_posix()
                raise BundleVerificationError(f"bundle file {relative!r} MUST NOT be a symlink")
        for name in names:
            entry = base / name
            relative = entry.relative_to(root).as_posix()
            if relative in _METADATA_NAMES:
                continue
            if entry.is_symlink():
                raise BundleVerificationError(f"bundle file {relative!r} MUST NOT be a symlink")
            if not entry.is_file():
                raise BundleVerificationError(f"bundle entry {relative!r} is not a regular file")
            actual.add(relative)
            try:
                total_bytes += entry.stat().st_size
            except OSError as exc:
                raise BundleVerificationError(
                    f"bundle file {relative!r} could not be measured: {exc}"
                ) from exc
            if total_bytes > max_total_bytes:
                raise BundleVerificationError("bundle exceeds the configured total size cap")
    if actual != listed:
        missing = sorted(listed - actual)
        extra = sorted(actual - listed)
        raise BundleVerificationError(
            f"bundle file set differs from manifest (missing={missing}, extra={extra})"
        )
    for relative, expected in manifest.files.items():
        digest = _file_digest(root / relative)
        if digest != expected:
            raise BundleVerificationError(f"bundle file digest mismatch for {relative!r}")
    return BundleVerification(
        bundle_version=manifest.bundle_version,
        release_channel=manifest.release_channel,
        manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=len(manifest.files),
        total_bytes=total_bytes,
    )


def _verify_signature(public_key_pem: bytes, manifest: bytes, signature: bytes) -> None:
    try:
        key = load_pem_public_key(public_key_pem)
    except ValueError as exc:
        raise BundleVerificationError("bundle public key is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise BundleVerificationError("bundle public key MUST be Ed25519")
    try:
        key.verify(signature, manifest)
    except InvalidSignature as exc:
        raise BundleVerificationError("bundle manifest signature is invalid") from exc


def _validate_compatibility(manifest: DeploymentBundleManifest, cli_version: str) -> None:
    current = _version_tuple(cli_version)
    if current < _version_tuple(manifest.min_cli_version):
        raise BundleVerificationError("bundle requires a newer CLI version")
    if manifest.max_cli_version is not None and current > _version_tuple(manifest.max_cli_version):
        raise BundleVerificationError("bundle does not support this CLI version")


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"bundle path {value!r} MUST be a normalized relative path")
    if "\\" in value:
        raise ValueError(f"bundle path {value!r} MUST use POSIX separators")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ValueError(f"version {value!r} MUST use MAJOR.MINOR.PATCH")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


__all__ = [
    "BUNDLE_SCHEMA",
    "BUNDLE_VERIFICATION_SCHEMA",
    "BundleVerification",
    "BundleVerificationError",
    "DeploymentBundleManifest",
    "ReleaseChannel",
    "verify_deployment_bundle",
]
