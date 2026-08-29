"""Verification for signed deployment bundle directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tarfile
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


def verify_bundle(
    root: Path,
    *,
    public_key_pem: bytes,
    cli_version: str = "0.1.0",
) -> BundleVerification:
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
    current = _semver(cli_version, "CLI version")
    minimum = _semver(_text(payload, "min_cli_version"), "minimum CLI version")
    maximum_value = payload["max_cli_version"]
    if maximum_value is not None and not isinstance(maximum_value, str):
        raise BundleVerificationError("deployment bundle maximum CLI version is invalid")
    maximum = (
        _semver(maximum_value, "maximum CLI version") if isinstance(maximum_value, str) else None
    )
    if current < minimum or (maximum is not None and current > maximum):
        raise BundleVerificationError("deployment bundle is incompatible with this CLI version")
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
            if not stat.S_ISREG(details.st_mode):
                raise BundleVerificationError("deployment bundle MUST contain regular files")
            if details.st_size > 512 * 1024 * 1024:
                raise BundleVerificationError("deployment bundle file exceeds its size limit")
            total_bytes += details.st_size
            if total_bytes > 8 * 1024 * 1024 * 1024:
                raise BundleVerificationError("deployment bundle exceeds its total size limit")
            observed[relative] = _sha256(candidate, expected=details)
    if dict(sorted(observed.items())) != dict(sorted(declared.items())):
        raise BundleVerificationError("deployment bundle exact file set or digest does not match")
    _verify_sbom(root, payload, declared)
    return BundleVerification(
        bundle_version=_text(payload, "bundle_version"),
        release_channel=_text(payload, "release_channel"),
        file_count=len(observed),
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
    )


def extract_bundle_archive(archive: Path, destination: Path) -> Path:
    """Extract one bounded regular-file bundle archive without path traversal."""

    if destination.exists():
        raise BundleVerificationError("deployment bundle destination already exists")
    destination.mkdir(parents=True, mode=0o700)
    total_bytes = 0
    roots: set[str] = set()
    try:
        with tarfile.open(archive, mode="r:gz") as stream:
            member_count = 0
            for member in stream:
                member_count += 1
                if member_count > 20_000:
                    raise BundleVerificationError(
                        "deployment bundle archive member count is invalid"
                    )
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or not path.parts
                ):
                    raise BundleVerificationError("deployment bundle archive path is invalid")
                roots.add(path.parts[0])
                if member.isdir():
                    continue
                if not member.isfile():
                    raise BundleVerificationError(
                        "deployment bundle archive MUST contain regular files"
                    )
                if member.size > 512 * 1024 * 1024:
                    raise BundleVerificationError(
                        "deployment bundle archive member exceeds its size limit"
                    )
                total_bytes += member.size
                if total_bytes > 8 * 1024 * 1024 * 1024:
                    raise BundleVerificationError(
                        "deployment bundle archive exceeds its total size limit"
                    )
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = stream.extractfile(member)
                if source is None:
                    raise BundleVerificationError("deployment bundle archive member is unreadable")
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with source, os.fdopen(descriptor, "wb") as output:
                    copied = 0
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        copied += len(chunk)
                        if copied > member.size:
                            raise BundleVerificationError(
                                "deployment bundle archive member exceeded its declared size"
                            )
                        output.write(chunk)
                    if copied != member.size:
                        raise BundleVerificationError(
                            "deployment bundle archive member size does not match"
                        )
            if member_count == 0:
                raise BundleVerificationError("deployment bundle archive member count is invalid")
        if len(roots) != 1:
            raise BundleVerificationError("deployment bundle archive MUST have one root")
        root = destination / roots.pop()
        if not root.is_dir():
            raise BundleVerificationError("deployment bundle archive root is invalid")
        return root
    except (tarfile.TarError, EOFError) as exc:
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
        raise BundleVerificationError("deployment bundle archive is invalid") from exc
    except BaseException:
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
        raise


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


def _verify_sbom(
    root: Path,
    manifest: dict[str, object],
    declared: dict[str, str],
) -> None:
    sbom_value = manifest["sbom_path"]
    if not isinstance(sbom_value, str):
        raise BundleVerificationError("deployment bundle sbom_path is invalid")
    sbom_path = _relative_path(sbom_value)
    if sbom_path not in declared:
        raise BundleVerificationError("deployment bundle SBOM is not declared")
    sbom = load_json_object(
        _read_regular(root / sbom_path, 16 * 1024 * 1024),
        label="deployment bundle SBOM",
        max_bytes=16 * 1024 * 1024,
    )
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise BundleVerificationError("deployment bundle SBOM format is unsupported")
    components = sbom.get("components")
    if not isinstance(components, list):
        raise BundleVerificationError("deployment bundle SBOM components are invalid")
    covered: dict[str, str] = {}
    for component in components:
        if not isinstance(component, dict):
            raise BundleVerificationError("deployment bundle SBOM component is invalid")
        name = component.get("name")
        hashes = component.get("hashes")
        if not isinstance(name, str) or not isinstance(hashes, list):
            raise BundleVerificationError("deployment bundle SBOM component is invalid")
        sha256_values = [
            item.get("content")
            for item in hashes
            if isinstance(item, dict) and item.get("alg") == "SHA-256"
        ]
        if len(sha256_values) != 1 or not isinstance(sha256_values[0], str):
            raise BundleVerificationError("deployment bundle SBOM SHA-256 is invalid")
        path = _relative_path(name)
        if path in covered:
            raise BundleVerificationError("deployment bundle SBOM contains duplicate paths")
        covered[path] = sha256_values[0]
    expected = {path: digest for path, digest in declared.items() if path != sbom_path}
    if covered != expected:
        raise BundleVerificationError("deployment bundle SBOM coverage does not match")


def _read_regular(path: Path, maximum: int) -> bytes:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
        raise BundleVerificationError("deployment bundle metadata is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read(maximum + 1)


def _sha256(path: Path, *, expected: os.stat_result) -> str:
    if not stat.S_ISREG(expected.st_mode):
        raise BundleVerificationError("deployment bundle MUST contain regular files")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    copied = 0
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require_same_file(expected, opened)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            copied += len(chunk)
            if copied > expected.st_size:
                raise BundleVerificationError("deployment bundle file grew during verification")
            digest.update(chunk)
        _require_same_file(opened, os.fstat(stream.fileno()))
    if copied != expected.st_size:
        raise BundleVerificationError("deployment bundle file size changed during verification")
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


def _semver(value: str, label: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)", value)
    if match is None:
        raise BundleVerificationError(f"deployment bundle {label} is not semantic version")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]
