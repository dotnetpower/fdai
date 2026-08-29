"""Verification for signed deployment bundle directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class BundleVerificationError(ValueError):
    """A signed deployment bundle is invalid or incompatible."""


@dataclass(frozen=True, slots=True)
class BundleVerification:
    """Sanitized signed-bundle verification result."""

    bundle_version: str
    release_channel: str
    file_count: int
    manifest_digest: str

    def to_json(self) -> str:
        """Return stable JSON."""

        return json.dumps(
            {
                "schema_version": "fdai.deployment-bundle-verification.v1",
                "bundle_version": self.bundle_version,
                "release_channel": self.release_channel,
                "file_count": self.file_count,
                "manifest_digest": self.manifest_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def verify_bundle(root: Path, *, public_key_pem: bytes) -> BundleVerification:
    """Verify signature, canonical manifest, exact file set, and every digest."""

    manifest_path = root / "manifest.json"
    signature_path = root / "manifest.json.sig"
    manifest = _read_regular(manifest_path, 4 * 1024 * 1024)
    signature = _read_regular(signature_path, 64)
    if len(signature) != 64:
        raise BundleVerificationError("deployment bundle signature MUST be 64 bytes")
    _verify_signature(public_key_pem, manifest, signature)
    payload = load_json_object(
        manifest, label="deployment bundle manifest", max_bytes=4 * 1024 * 1024
    )
    expected = {
        "schema_version",
        "bundle_version",
        "release_channel",
        "min_cli_version",
        "max_cli_version",
        "sbom_path",
        "files",
    }
    if set(payload) != expected or payload["schema_version"] != "fdai.deployment.bundle.v1":
        raise BundleVerificationError("deployment bundle manifest schema does not match")
    if canonical_bytes(payload) + b"\n" != manifest:
        raise BundleVerificationError("deployment bundle manifest is not canonical")
    files_value = payload["files"]
    if not isinstance(files_value, dict) or not files_value:
        raise BundleVerificationError("deployment bundle files MUST be a non-empty object")
    declared: dict[str, str] = {}
    for raw_path, raw_digest in files_value.items():
        if not isinstance(raw_path, str) or not isinstance(raw_digest, str):
            raise BundleVerificationError("deployment bundle file entry is invalid")
        path = _relative_path(raw_path)
        if _DIGEST.fullmatch(raw_digest) is None:
            raise BundleVerificationError("deployment bundle file digest is invalid")
        declared[path] = raw_digest
    observed: dict[str, str] = {}
    total_bytes = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in directories):
            raise BundleVerificationError("deployment bundle MUST NOT contain symlinks")
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            if relative in {"manifest.json", "manifest.json.sig"}:
                continue
            if len(observed) >= 20_000:
                raise BundleVerificationError("deployment bundle exceeds its file count limit")
            details = candidate.lstat()
            if details.st_size > 512 * 1024 * 1024:
                raise BundleVerificationError("deployment bundle file exceeds its size limit")
            total_bytes += details.st_size
            if total_bytes > 8 * 1024 * 1024 * 1024:
                raise BundleVerificationError("deployment bundle exceeds its total size limit")
            observed[relative] = _sha256(candidate, expected=details)
    if dict(sorted(observed.items())) != dict(sorted(declared.items())):
        raise BundleVerificationError("deployment bundle exact file set or digest does not match")
    return BundleVerification(
        bundle_version=_text(payload, "bundle_version"),
        release_channel=_text(payload, "release_channel"),
        file_count=len(observed),
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
    )


def _verify_signature(public_pem: bytes, document: bytes, signature: bytes) -> None:
    try:
        key = load_pem_public_key(public_pem)
    except (TypeError, ValueError) as exc:
        raise BundleVerificationError("deployment bundle public key is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise BundleVerificationError("deployment bundle public key MUST be Ed25519")
    try:
        key.verify(signature, document)
    except InvalidSignature as exc:
        raise BundleVerificationError("deployment bundle signature is invalid") from exc


def _read_regular(path: Path, maximum: int) -> bytes:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
        raise BundleVerificationError("deployment bundle metadata is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read(maximum + 1)


def _sha256(path: Path, *, expected: os.stat_result) -> str:
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
        raise BundleVerificationError("deployment bundle file changed during verification")


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BundleVerificationError("deployment bundle path is invalid")
    return path.as_posix()


def _text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise BundleVerificationError(f"deployment bundle {field} MUST be text")
    return item
