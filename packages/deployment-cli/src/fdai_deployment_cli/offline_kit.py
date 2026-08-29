"""Signed, exact-file-set offline kit construction and verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object

MANIFEST_NAME: Final = "offline-kit.json"
SIGNATURE_NAME: Final = "offline-kit.json.sig"
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_FILES = 20_000
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class OfflineKitVerificationError(ValueError):
    """The offline kit failed trust, compatibility, or content checks."""


@dataclass(frozen=True, slots=True)
class OfflineKitVerification:
    """Sanitized result of a successful kit verification."""

    kit_version: str
    cli_version: str
    bundle_version: str
    platform_tag: str
    file_count: int
    total_bytes: int
    manifest_digest: str

    def to_json(self) -> str:
        """Return stable, non-secret machine output."""

        return json.dumps(
            {
                "schema_version": "fdai.offline-kit-verification.v1",
                "kit_version": self.kit_version,
                "cli_version": self.cli_version,
                "bundle_version": self.bundle_version,
                "platform_tag": self.platform_tag,
                "file_count": self.file_count,
                "total_bytes": self.total_bytes,
                "manifest_digest": self.manifest_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


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
) -> bytes:
    """Build canonical manifest bytes from the exact staged tree."""

    required = {
        "python_wheel": _relative_path(python_wheel),
        "deployment_bundle": _relative_path(deployment_bundle),
        "terraform_binary": _relative_path(terraform_binary),
        "provider_mirror_prefix": _relative_path(provider_mirror_prefix),
        "opa_binary": _relative_path(opa_binary),
        "sbom_path": _relative_path(sbom_path),
    }
    files, _total = _scan_tree(root)
    for label in (
        "python_wheel",
        "deployment_bundle",
        "terraform_binary",
        "opa_binary",
        "sbom_path",
    ):
        if required[label] not in files:
            raise OfflineKitVerificationError(f"offline kit is missing {label}")
    prefix = required["provider_mirror_prefix"].rstrip("/") + "/"
    if not any(path.startswith(prefix) for path in files):
        raise OfflineKitVerificationError("offline kit provider mirror is empty")
    return canonical_bytes(
        {
            "schema_version": "fdai.offline-kit.v1",
            "kit_version": kit_version,
            "cli_version": cli_version,
            "bundle_version": bundle_version,
            "platform_tag": platform_tag,
            **required,
            "files": files,
        }
    )


def verify_offline_kit(
    root: Path,
    *,
    release_root_pem: bytes,
    cli_version: str,
    platform_tag: str,
) -> OfflineKitVerification:
    """Verify signature before parsing, then compatibility, exact files, and digests."""

    manifest_path = root / MANIFEST_NAME
    signature_path = root / SIGNATURE_NAME
    manifest = _read_regular(manifest_path, _MAX_MANIFEST_BYTES)
    signature = _read_regular(signature_path, 64)
    if len(signature) != 64:
        raise OfflineKitVerificationError("offline kit signature MUST be 64 bytes")
    _verify_signature(release_root_pem, manifest, signature)
    try:
        payload = load_json_object(
            manifest,
            label="offline kit manifest",
            max_bytes=_MAX_MANIFEST_BYTES,
        )
        expected = {
            "schema_version",
            "kit_version",
            "cli_version",
            "bundle_version",
            "platform_tag",
            "python_wheel",
            "deployment_bundle",
            "terraform_binary",
            "provider_mirror_prefix",
            "opa_binary",
            "sbom_path",
            "files",
        }
        if set(payload) != expected or payload["schema_version"] != "fdai.offline-kit.v1":
            raise OfflineKitVerificationError("offline kit manifest schema does not match")
        if payload["cli_version"] != cli_version:
            raise OfflineKitVerificationError("offline kit CLI version does not match")
        if payload["platform_tag"] != platform_tag:
            raise OfflineKitVerificationError("offline kit platform does not match")
        files_value = payload["files"]
        if not isinstance(files_value, dict) or not files_value:
            raise OfflineKitVerificationError("offline kit files MUST be a non-empty object")
        declared: dict[str, str] = {}
        for raw_path, raw_digest in files_value.items():
            if not isinstance(raw_path, str) or not isinstance(raw_digest, str):
                raise OfflineKitVerificationError("offline kit file entries are invalid")
            path = _relative_path(raw_path)
            if _DIGEST.fullmatch(raw_digest) is None:
                raise OfflineKitVerificationError("offline kit file digest is invalid")
            declared[path] = raw_digest
        required_paths = (
            "python_wheel",
            "deployment_bundle",
            "terraform_binary",
            "opa_binary",
            "sbom_path",
        )
        for field in required_paths:
            value = payload[field]
            if not isinstance(value, str) or _relative_path(value) not in declared:
                raise OfflineKitVerificationError(f"offline kit {field} is not declared")
        prefix_value = payload["provider_mirror_prefix"]
        if not isinstance(prefix_value, str):
            raise OfflineKitVerificationError("offline kit provider mirror prefix is invalid")
        prefix = _relative_path(prefix_value).rstrip("/") + "/"
        if not any(path.startswith(prefix) for path in declared):
            raise OfflineKitVerificationError("offline kit provider mirror is empty")
        observed, total = _scan_tree(root)
        if observed != declared:
            raise OfflineKitVerificationError("offline kit exact file set or digest does not match")
        if canonical_bytes(payload) != manifest:
            raise OfflineKitVerificationError("offline kit manifest is not canonical")
        return OfflineKitVerification(
            kit_version=_payload_text(payload, "kit_version"),
            cli_version=_payload_text(payload, "cli_version"),
            bundle_version=_payload_text(payload, "bundle_version"),
            platform_tag=_payload_text(payload, "platform_tag"),
            file_count=len(observed),
            total_bytes=total,
            manifest_digest=hashlib.sha256(manifest).hexdigest(),
        )
    except OfflineKitVerificationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise OfflineKitVerificationError("offline kit manifest is invalid") from exc


def _scan_tree(root: Path) -> tuple[dict[str, str], int]:
    if root.is_symlink() or not root.is_dir():
        raise OfflineKitVerificationError("offline kit root MUST be a directory")
    files: dict[str, str] = {}
    total = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directories:
            candidate = base / name
            if candidate.is_symlink():
                raise OfflineKitVerificationError("offline kit MUST NOT contain symlinks")
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            if relative in {MANIFEST_NAME, SIGNATURE_NAME}:
                continue
            if candidate.is_symlink():
                raise OfflineKitVerificationError("offline kit MUST NOT contain symlinks")
            if len(files) >= _MAX_FILES:
                raise OfflineKitVerificationError("offline kit exceeds its file count limit")
            details = candidate.lstat()
            if not stat.S_ISREG(details.st_mode):
                raise OfflineKitVerificationError("offline kit MUST contain only regular files")
            if details.st_size > _MAX_FILE_BYTES:
                raise OfflineKitVerificationError("offline kit file exceeds its size limit")
            total += details.st_size
            if total > _MAX_TOTAL_BYTES:
                raise OfflineKitVerificationError("offline kit exceeds its total size limit")
            files[relative] = _sha256_nofollow(candidate)
    return dict(sorted(files.items())), total


def _sha256_nofollow(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_regular(path: Path, maximum: int) -> bytes:
    try:
        details = path.lstat()
    except OSError as exc:
        raise OfflineKitVerificationError("offline kit metadata is unavailable") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
        raise OfflineKitVerificationError("offline kit metadata is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read(maximum + 1)


def _verify_signature(public_pem: bytes, document: bytes, signature: bytes) -> None:
    try:
        key = load_pem_public_key(public_pem)
    except (TypeError, ValueError) as exc:
        raise OfflineKitVerificationError("offline kit release root is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise OfflineKitVerificationError("offline kit release root MUST be Ed25519")
    try:
        key.verify(signature, document)
    except InvalidSignature as exc:
        raise OfflineKitVerificationError("offline kit signature is invalid") from exc


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise OfflineKitVerificationError("offline kit path is invalid")
    return path.as_posix()


def _payload_text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise OfflineKitVerificationError(f"offline kit {field} MUST be text")
    return item
