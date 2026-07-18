#!/usr/bin/env python3
"""Build a deterministic, signed FDAI deployment bundle from tracked sources."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ROOTS: Final[tuple[str, ...]] = (
    "infra",
    "policies",
    "rule-catalog/schema",
    "rule-catalog/profiles",
    "rule-catalog/risk-classification.yaml",
)
_FORBIDDEN_NAMES = frozenset({"bootstrap.tfvars", "terraform.tfstate", "terraform.tfstate.backup"})
_FORBIDDEN_SUFFIXES = (".plan", ".tfvars", ".pem", ".key")
_MAX_SOURCE_BYTES: Final[int] = 256 * 1024 * 1024


class BundleBuildError(RuntimeError):
    """A deployment bundle could not be built reproducibly and safely."""


def build_bundle(
    source_root: Path,
    destination: Path,
    *,
    source_paths: tuple[str, ...],
    bundle_version: str,
    release_channel: str,
    min_cli_version: str,
    max_cli_version: str | None,
    private_key_pem: bytes,
    source_date_epoch: int,
) -> None:
    """Create one normalized signed bundle directory from explicit source paths."""
    if source_date_epoch < 0:
        raise BundleBuildError("SOURCE_DATE_EPOCH MUST be non-negative")
    if destination.exists():
        raise BundleBuildError("bundle destination already exists")
    private_key = _private_key(private_key_pem)
    normalized_paths = _validate_paths(source_paths)
    destination.mkdir(parents=True, mode=0o755)
    file_digests: dict[str, str] = {}
    total_bytes = 0
    try:
        for relative in normalized_paths:
            source = source_root / relative
            if source.is_symlink() or not source.is_file():
                raise BundleBuildError(f"bundle source {relative!r} MUST be a regular file")
            total_bytes += source.stat().st_size
            if total_bytes > _MAX_SOURCE_BYTES:
                raise BundleBuildError("bundle sources exceed the size limit")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            _normalize_file(target, source_date_epoch)
            file_digests[relative] = _sha256(target)

        sbom_path = "sbom.cdx.json"
        sbom = _sbom(file_digests)
        _write_json(destination / sbom_path, sbom, source_date_epoch)
        file_digests[sbom_path] = _sha256(destination / sbom_path)
        manifest = {
            "schema_version": "fdai.deployment.bundle.v1",
            "bundle_version": bundle_version,
            "release_channel": release_channel,
            "min_cli_version": min_cli_version,
            "max_cli_version": max_cli_version,
            "sbom_path": sbom_path,
            "files": dict(sorted(file_digests.items())),
        }
        manifest_path = destination / "manifest.json"
        _write_json(manifest_path, manifest, source_date_epoch)
        signature_path = destination / "manifest.json.sig"
        signature_path.write_bytes(private_key.sign(manifest_path.read_bytes()))
        _normalize_file(signature_path, source_date_epoch)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def write_reproducible_archive(
    bundle_root: Path,
    archive_path: Path,
    *,
    bundle_version: str,
    source_date_epoch: int,
) -> None:
    """Write a deterministic gzip-compressed tar archive of one built bundle."""
    if archive_path.exists():
        raise BundleBuildError("bundle archive already exists")
    prefix = f"fdai-deployment-bundle-{bundle_version}"
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=source_date_epoch) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.GNU_FORMAT) as archive:
                _add_directory(archive, prefix, source_date_epoch)
                directories = sorted(
                    {
                        parent.as_posix()
                        for path in bundle_root.rglob("*")
                        for parent in path.relative_to(bundle_root).parents
                        if parent.as_posix() != "."
                    }
                )
                for directory in directories:
                    _add_directory(archive, f"{prefix}/{directory}", source_date_epoch)
                for path in sorted(bundle_root.rglob("*")):
                    if path.is_dir():
                        continue
                    if path.is_symlink() or not path.is_file():
                        raise BundleBuildError("bundle archive input MUST contain regular files")
                    relative = path.relative_to(bundle_root).as_posix()
                    info = tarfile.TarInfo(f"{prefix}/{relative}")
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.mtime = source_date_epoch
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)


def public_key_pem(private_key_pem: bytes) -> bytes:
    return (
        _private_key(private_key_pem)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _tracked_paths(source_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "ls-files", "-z", "--", *_ROOTS],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleBuildError("tracked bundle source discovery failed") from exc
    return tuple(path.decode("utf-8") for path in completed.stdout.split(b"\0") if path)


def _validate_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    if not paths:
        raise BundleBuildError("bundle source list MUST NOT be empty")
    normalized: set[str] = set()
    for value in paths:
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise BundleBuildError(f"bundle source path {value!r} is invalid")
        if "\\" in value or path.name in _FORBIDDEN_NAMES or value.endswith(_FORBIDDEN_SUFFIXES):
            raise BundleBuildError(f"bundle source path {value!r} is forbidden")
        if not any(value == root or value.startswith(f"{root}/") for root in _ROOTS):
            raise BundleBuildError(f"bundle source path {value!r} is outside the allowlist")
        normalized.add(value)
    return tuple(sorted(normalized))


def _private_key(value: bytes) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(value, password=None)
    except (TypeError, ValueError) as exc:
        raise BundleBuildError("bundle signing key is invalid") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise BundleBuildError("bundle signing key MUST be Ed25519")
    return key


def _sbom(files: dict[str, str]) -> dict[str, object]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": [
            {
                "type": "file",
                "name": path,
                "hashes": [{"alg": "SHA-256", "content": digest}],
            }
            for path, digest in sorted(files.items())
        ],
    }


def _write_json(path: Path, value: object, epoch: int) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _normalize_file(path, epoch)


def _normalize_file(path: Path, epoch: int) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    os.utime(path, (epoch, epoch))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_directory(archive: tarfile.TarFile, name: str, epoch: int) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = epoch
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key-output", type=Path, required=True)
    parser.add_argument("--bundle-version", required=True)
    parser.add_argument(
        "--release-channel",
        choices=("stable", "beta", "development"),
        required=True,
    )
    parser.add_argument("--min-cli-version", required=True)
    parser.add_argument("--max-cli-version", default=None)
    args = parser.parse_args(argv)
    try:
        private_key = args.private_key.read_bytes()
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
        build_bundle(
            args.source,
            args.destination,
            source_paths=_tracked_paths(args.source),
            bundle_version=args.bundle_version,
            release_channel=args.release_channel,
            min_cli_version=args.min_cli_version,
            max_cli_version=args.max_cli_version,
            private_key_pem=private_key,
            source_date_epoch=epoch,
        )
        write_reproducible_archive(
            args.destination,
            args.archive,
            bundle_version=args.bundle_version,
            source_date_epoch=epoch,
        )
        args.public_key_output.write_bytes(public_key_pem(private_key))
        _normalize_file(args.public_key_output, epoch)
    except (OSError, ValueError, BundleBuildError) as exc:
        print(f"bundle build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
