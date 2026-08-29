"""Signed, exact-file-set offline kit construction and verification."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
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
    python_tag: str
    libc_tag: str
    file_count: int
    total_bytes: int
    manifest_digest: str
    terraform_binary: str
    provider_mirror_prefix: str
    deployment_bundle: str
    file_digests: tuple[tuple[str, str], ...]

    def to_json(self) -> str:
        """Return stable, non-secret machine output."""

        return json.dumps(
            {
                "schema_version": "fdai.offline-kit-verification.v1",
                "kit_version": self.kit_version,
                "cli_version": self.cli_version,
                "bundle_version": self.bundle_version,
                "platform_tag": self.platform_tag,
                "python_tag": self.python_tag,
                "libc_tag": self.libc_tag,
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
    python_tag: str | None = None,
    libc_tag: str | None = None,
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
            "python_tag": python_tag or _runtime_python_tag(),
            "libc_tag": libc_tag or _runtime_libc_tag(),
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
    python_tag: str | None = None,
    libc_tag: str | None = None,
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
            "python_tag",
            "libc_tag",
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
        if payload["python_tag"] != (python_tag or _runtime_python_tag()):
            raise OfflineKitVerificationError("offline kit Python ABI does not match")
        if payload["libc_tag"] != (libc_tag or _runtime_libc_tag()):
            raise OfflineKitVerificationError("offline kit libc does not match")
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
        _verify_sbom(root, payload, declared)
        if canonical_bytes(payload) != manifest:
            raise OfflineKitVerificationError("offline kit manifest is not canonical")
        return OfflineKitVerification(
            kit_version=_payload_text(payload, "kit_version"),
            cli_version=_payload_text(payload, "cli_version"),
            bundle_version=_payload_text(payload, "bundle_version"),
            platform_tag=_payload_text(payload, "platform_tag"),
            python_tag=_payload_text(payload, "python_tag"),
            libc_tag=_payload_text(payload, "libc_tag"),
            file_count=len(observed),
            total_bytes=total,
            manifest_digest=hashlib.sha256(manifest).hexdigest(),
            terraform_binary=_payload_text(payload, "terraform_binary"),
            provider_mirror_prefix=_payload_text(payload, "provider_mirror_prefix"),
            deployment_bundle=_payload_text(payload, "deployment_bundle"),
            file_digests=tuple(sorted(declared.items())),
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
            files[relative] = _sha256_nofollow(candidate, expected=details)
    return dict(sorted(files.items())), total


@dataclass(frozen=True, slots=True)
class MaterializedOfflineArtifacts:
    """Private verified copies used after kit verification."""

    terraform_binary: Path
    provider_mirror: Path
    deployment_bundle: Path
    python_wheels: Path


def materialize_verified_artifacts(
    root: Path,
    verification: OfflineKitVerification,
    destination: Path,
) -> MaterializedOfflineArtifacts:
    """Copy executable inputs to a private tree and recheck signed digests."""

    if destination.exists():
        raise OfflineKitVerificationError("offline artifact destination already exists")
    destination.mkdir(parents=True, mode=0o700)
    destination.chmod(0o700)
    digests = dict(verification.file_digests)
    prefix = verification.provider_mirror_prefix.rstrip("/") + "/"
    python_prefix = "python/"
    selected = {
        verification.terraform_binary,
        verification.deployment_bundle,
        *(path for path in digests if path.startswith(prefix)),
        *(path for path in digests if path.startswith(python_prefix)),
    }
    for relative in sorted(selected):
        expected = digests.get(relative)
        if expected is None:
            raise OfflineKitVerificationError("verified offline artifact is not declared")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _copy_verified_file(root / relative, target, expected_digest=expected)
    terraform = destination / verification.terraform_binary
    terraform.chmod(0o700)
    return MaterializedOfflineArtifacts(
        terraform_binary=terraform,
        provider_mirror=destination / verification.provider_mirror_prefix,
        deployment_bundle=destination / verification.deployment_bundle,
        python_wheels=destination / "python",
    )


def _copy_verified_file(source: Path, target: Path, *, expected_digest: str) -> None:
    details = source.lstat()
    if not stat.S_ISREG(details.st_mode):
        raise OfflineKitVerificationError("verified offline artifact MUST be a regular file")
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    output_descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    digest = hashlib.sha256()
    try:
        with (
            os.fdopen(descriptor, "rb") as input_stream,
            os.fdopen(output_descriptor, "wb") as output_stream,
        ):
            opened = os.fstat(input_stream.fileno())
            _require_same_file(details, opened)
            for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                digest.update(chunk)
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
            _require_same_file(opened, os.fstat(input_stream.fileno()))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != expected_digest:
        target.unlink(missing_ok=True)
        raise OfflineKitVerificationError("verified offline artifact digest changed")


def _sha256_nofollow(path: Path, *, expected: os.stat_result) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require_same_file(expected, opened)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        _require_same_file(opened, os.fstat(stream.fileno()))
    return digest.hexdigest()


def _require_same_file(expected: os.stat_result, observed: os.stat_result) -> None:
    if (
        not stat.S_ISREG(observed.st_mode)
        or expected.st_dev != observed.st_dev
        or expected.st_ino != observed.st_ino
        or expected.st_size != observed.st_size
        or expected.st_mtime_ns != observed.st_mtime_ns
    ):
        raise OfflineKitVerificationError("offline kit file changed during verification")


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


def _verify_sbom(
    root: Path,
    manifest: dict[str, object],
    declared: dict[str, str],
) -> None:
    sbom_value = manifest["sbom_path"]
    if not isinstance(sbom_value, str):
        raise OfflineKitVerificationError("offline kit sbom_path is invalid")
    sbom_path = _relative_path(sbom_value)
    sbom = load_json_object(
        _read_regular(root / sbom_path, 16 * 1024 * 1024),
        label="offline kit SBOM",
        max_bytes=16 * 1024 * 1024,
    )
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise OfflineKitVerificationError("offline kit SBOM format is unsupported")
    components = sbom.get("components")
    if not isinstance(components, list):
        raise OfflineKitVerificationError("offline kit SBOM components are invalid")
    covered: dict[str, str] = {}
    for component in components:
        if not isinstance(component, dict):
            raise OfflineKitVerificationError("offline kit SBOM component is invalid")
        name = component.get("name")
        hashes = component.get("hashes")
        if not isinstance(name, str) or not isinstance(hashes, list):
            raise OfflineKitVerificationError("offline kit SBOM component is invalid")
        sha256_values = [
            item.get("content")
            for item in hashes
            if isinstance(item, dict) and item.get("alg") == "SHA-256"
        ]
        if len(sha256_values) != 1 or not isinstance(sha256_values[0], str):
            raise OfflineKitVerificationError("offline kit SBOM SHA-256 is invalid")
        path = _relative_path(name)
        if path in covered:
            raise OfflineKitVerificationError("offline kit SBOM contains duplicate paths")
        covered[path] = sha256_values[0]
    expected = {path: digest for path, digest in declared.items() if path != sbom_path}
    if covered != expected:
        raise OfflineKitVerificationError("offline kit SBOM coverage does not match")


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


def _runtime_python_tag() -> str:
    return f"{sys.implementation.name}-{sys.version_info.major}{sys.version_info.minor}"


def _runtime_libc_tag() -> str:
    name, version = platform.libc_ver()
    normalized_name = name.casefold().strip()
    normalized_version = version.casefold().strip()
    if (
        re.fullmatch(r"[a-z0-9._-]+", normalized_name) is None
        or re.fullmatch(r"[a-z0-9._-]+", normalized_version) is None
    ):
        raise OfflineKitVerificationError("runtime libc identity is unavailable")
    return f"{normalized_name}-{normalized_version}"
