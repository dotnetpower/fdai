"""Offline deployment-kit manifest construction and verification.

The module owns one contract - ``fdai.deployment.offline-kit.v1`` - in both
directions. :func:`build_offline_kit_manifest` mints the canonical signable
bytes for a staged kit and :func:`verify_offline_kit` re-establishes trust in
an unpacked kit. Both apply the same content rules, so the builder refuses to
mint a manifest for a tree that verification would later reject.

Signing is deliberately out of scope: the release private key never reaches
library code (see ``scripts/deployment/release/build-offline-kit.py``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import BaseModel, ConfigDict, Field, ValidationError

OFFLINE_KIT_SCHEMA: Final = "fdai.deployment.offline-kit.v1"
OFFLINE_KIT_VERIFICATION_SCHEMA: Final = "fdai.deployment-cli.offline-kit-verification.v1"
MANIFEST_NAME: Final = "offline-kit.json"
SIGNATURE_NAME: Final = "offline-kit.json.sig"
_METADATA_NAMES: Final = frozenset({MANIFEST_NAME, SIGNATURE_NAME})
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_PLATFORM = re.compile(r"^[a-z0-9]+(?:-[a-z0-9_]+)+$")
_DEFAULT_MAX_TOTAL_BYTES: Final = 4 * 1024 * 1024 * 1024
_DEFAULT_MAX_FILES: Final = 20_000
_MAX_MANIFEST_BYTES: Final = 4 * 1024 * 1024
_MAX_SIGNATURE_BYTES: Final = 4 * 1024


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OfflineKitManifest(_ManifestModel):
    schema_version: Literal["fdai.deployment.offline-kit.v1"] = OFFLINE_KIT_SCHEMA
    kit_version: str
    cli_version: str
    bundle_version: str
    platform_tag: str
    python_wheel: str
    deployment_bundle: str
    terraform_binary: str
    provider_mirror_prefix: str
    opa_binary: str
    sbom_path: str
    files: dict[str, str] = Field(min_length=1, max_length=_DEFAULT_MAX_FILES)

    def model_post_init(self, __context: object) -> None:
        for version in (self.kit_version, self.cli_version, self.bundle_version):
            _validate_version(version)
        if _PLATFORM.fullmatch(self.platform_tag) is None:
            raise ValueError("platform_tag is invalid")
        for path, digest in self.files.items():
            _validate_relative_path(path)
            if _DIGEST.fullmatch(digest) is None:
                raise ValueError(f"offline kit digest for {path!r} is invalid")
        required_files = (
            self.python_wheel,
            self.deployment_bundle,
            self.terraform_binary,
            self.opa_binary,
            self.sbom_path,
        )
        for path in required_files:
            _validate_relative_path(path)
            if path not in self.files:
                raise ValueError(f"required offline kit artifact {path!r} is not listed")
        _validate_relative_path(self.provider_mirror_prefix)
        prefix = self.provider_mirror_prefix.rstrip("/") + "/"
        if not any(path.startswith(prefix) for path in self.files):
            raise ValueError("provider mirror prefix contains no listed artifact")
        if not self.python_wheel.endswith(".whl"):
            raise ValueError("python_wheel MUST reference a wheel")
        if not self.deployment_bundle.endswith(".tar.gz"):
            raise ValueError("deployment_bundle MUST reference a tar.gz archive")
        if not self.sbom_path.endswith(".json"):
            raise ValueError("sbom_path MUST reference JSON")


@dataclass(frozen=True, slots=True)
class OfflineKitVerification:
    kit_version: str
    cli_version: str
    bundle_version: str
    platform_tag: str
    manifest_digest: str
    file_count: int
    total_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_version": self.bundle_version,
            "cli_version": self.cli_version,
            "file_count": self.file_count,
            "kit_version": self.kit_version,
            "manifest_digest": self.manifest_digest,
            "platform_tag": self.platform_tag,
            "schema_version": OFFLINE_KIT_VERIFICATION_SCHEMA,
            "total_bytes": self.total_bytes,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )


class OfflineKitVerificationError(ValueError):
    """The offline kit failed trust, compatibility, or content verification."""


def build_offline_kit_manifest(
    root: Path,
    *,
    kit_version: str,
    cli_version: str,
    bundle_version: str,
    platform_tag: str,
    python_wheel: str,
    deployment_bundle: str,
    terraform_binary: str,
    provider_mirror_prefix: str,
    opa_binary: str,
    sbom_path: str,
    max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    max_files: int = _DEFAULT_MAX_FILES,
) -> bytes:
    """Return canonical signable manifest bytes for one staged offline kit.

    The staged tree is read exactly as :func:`verify_offline_kit` reads it:
    symlinks, non-regular entries, and out-of-bound trees are rejected instead
    of being described, so a manifest can never attest to content that the
    verifier would refuse. The caller signs the returned bytes verbatim; this
    function never touches a private key and never writes to ``root``.
    """
    if max_total_bytes < 1 or max_files < 1:
        raise ValueError("offline kit limits MUST be positive")
    if root.is_symlink() or not root.is_dir():
        raise OfflineKitVerificationError("offline kit root MUST be a regular directory")
    staged, _total_bytes = _scan_kit_files(
        root,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
    )
    if not staged:
        raise OfflineKitVerificationError("offline kit stages no artifact")
    manifest = OfflineKitManifest(
        kit_version=kit_version,
        cli_version=cli_version,
        bundle_version=bundle_version,
        platform_tag=platform_tag,
        python_wheel=python_wheel,
        deployment_bundle=deployment_bundle,
        terraform_binary=terraform_binary,
        provider_mirror_prefix=provider_mirror_prefix,
        opa_binary=opa_binary,
        sbom_path=sbom_path,
        files={relative: _file_digest(root / relative) for relative in sorted(staged)},
    )
    return canonical_manifest_bytes(manifest)


def canonical_manifest_bytes(manifest: OfflineKitManifest) -> bytes:
    """Serialize a manifest to the exact byte sequence that is signed."""
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload.encode("utf-8") + b"\n"


def verify_offline_kit(
    root: Path,
    *,
    release_root_pem: bytes,
    cli_version: str,
    platform_tag: str,
    max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    max_files: int = _DEFAULT_MAX_FILES,
) -> OfflineKitVerification:
    """Verify one unpacked offline kit without executing or following its contents."""
    _validate_version(cli_version)
    if _PLATFORM.fullmatch(platform_tag) is None:
        raise ValueError("platform_tag is invalid")
    if max_total_bytes < 1 or max_files < 1:
        raise ValueError("offline kit limits MUST be positive")
    manifest_path = root / MANIFEST_NAME
    signature_path = root / SIGNATURE_NAME
    if root.is_symlink() or not root.is_dir():
        raise OfflineKitVerificationError("offline kit root MUST be a regular directory")
    if any(path.is_symlink() or not path.is_file() for path in (manifest_path, signature_path)):
        raise OfflineKitVerificationError("offline kit metadata MUST be regular files")
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise OfflineKitVerificationError("offline kit manifest exceeds the size limit")
        if signature_path.stat().st_size > _MAX_SIGNATURE_BYTES:
            raise OfflineKitVerificationError("offline kit signature exceeds the size limit")
        manifest_bytes = manifest_path.read_bytes()
        signature = signature_path.read_bytes()
    except OSError as exc:
        raise OfflineKitVerificationError("offline kit manifest or signature is missing") from exc
    _verify_signature(release_root_pem, manifest_bytes, signature)
    try:
        manifest = OfflineKitManifest.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise OfflineKitVerificationError("offline kit manifest is invalid") from exc
    if manifest.cli_version != cli_version:
        raise OfflineKitVerificationError("offline kit CLI version does not match")
    if manifest.platform_tag != platform_tag:
        raise OfflineKitVerificationError("offline kit platform does not match")

    listed = set(manifest.files)
    actual, total_bytes = _scan_kit_files(
        root,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
    )
    if actual != listed:
        missing = sorted(listed - actual)
        extra = sorted(actual - listed)
        raise OfflineKitVerificationError(
            f"offline kit file set differs from manifest (missing={missing}, extra={extra})"
        )
    for relative, expected in manifest.files.items():
        if _file_digest(root / relative) != expected:
            raise OfflineKitVerificationError(f"offline kit file digest mismatch for {relative!r}")
    return OfflineKitVerification(
        kit_version=manifest.kit_version,
        cli_version=manifest.cli_version,
        bundle_version=manifest.bundle_version,
        platform_tag=manifest.platform_tag,
        manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=len(manifest.files),
        total_bytes=total_bytes,
    )


def _scan_kit_files(
    root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
) -> tuple[set[str], int]:
    """Enumerate payload files under ``root`` without following any symlink."""
    found: set[str] = set()
    total_bytes = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative in _METADATA_NAMES:
            continue
        if path.is_symlink():
            raise OfflineKitVerificationError(
                f"offline kit file {relative!r} MUST NOT be a symlink"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise OfflineKitVerificationError(
                f"offline kit entry {relative!r} is not a regular file"
            )
        found.add(relative)
        if len(found) > max_files:
            raise OfflineKitVerificationError("offline kit exceeds the file-count limit")
        total_bytes += path.stat().st_size
        if total_bytes > max_total_bytes:
            raise OfflineKitVerificationError("offline kit exceeds the total-size limit")
    return found, total_bytes


def _verify_signature(public_key_pem: bytes, manifest: bytes, signature: bytes) -> None:
    try:
        key = load_pem_public_key(public_key_pem)
    except ValueError as exc:
        raise OfflineKitVerificationError("offline kit release root is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise OfflineKitVerificationError("offline kit release root MUST be Ed25519")
    try:
        key.verify(signature, manifest)
    except InvalidSignature as exc:
        raise OfflineKitVerificationError("offline kit manifest signature is invalid") from exc


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"offline kit path {value!r} MUST be a normalized relative path")
    if "\\" in value:
        raise ValueError(f"offline kit path {value!r} MUST use POSIX separators")


def _validate_version(value: str) -> None:
    if _VERSION.fullmatch(value) is None:
        raise ValueError(f"version {value!r} MUST use MAJOR.MINOR.PATCH")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise OfflineKitVerificationError("offline kit no-follow file open is unavailable")
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow)
    except OSError as exc:
        raise OfflineKitVerificationError("offline kit artifact MUST be a regular file") from exc
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OfflineKitVerificationError("offline kit artifact MUST be a regular file")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "MANIFEST_NAME",
    "OFFLINE_KIT_SCHEMA",
    "OFFLINE_KIT_VERIFICATION_SCHEMA",
    "SIGNATURE_NAME",
    "OfflineKitManifest",
    "OfflineKitVerification",
    "OfflineKitVerificationError",
    "build_offline_kit_manifest",
    "canonical_manifest_bytes",
    "verify_offline_kit",
]
