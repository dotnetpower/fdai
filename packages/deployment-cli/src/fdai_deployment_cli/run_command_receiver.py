"""Receive one digest-bound execution bundle inside an eligible WSL host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes

_DIGEST = re.compile(r"[0-9a-f]{64}")
_OPERATION_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
_ROOT = "fdai-execution"
_MANIFEST = f"{_ROOT}/manifest.json"
_RECEIPT = ".fdai-execution-receipt.json"
_RETAINED_MANIFEST = ".fdai-execution-manifest.json"
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_MEMBERS = 20_000


def receive_execution_bundle(
    archive: Path | None,
    destination: Path,
    *,
    expected_digest: str,
    expected_operation_id: str,
    claim_digest: str = "0" * 64,
    verify_existing: bool = False,
) -> dict[str, object]:
    """Verify and atomically extract one fixed-inventory execution bundle."""

    if _DIGEST.fullmatch(expected_digest) is None:
        raise ValueError("execution bundle digest is invalid")
    if _DIGEST.fullmatch(claim_digest) is None:
        raise ValueError("execution bundle claim digest is invalid")
    if _OPERATION_ID.fullmatch(expected_operation_id) is None:
        raise ValueError("execution bundle operation id is invalid")
    if destination.exists() or destination.is_symlink():
        if not verify_existing:
            raise ValueError("execution bundle destination already exists")
        return _verify_existing(
            destination,
            bundle_digest=expected_digest,
            operation_id=expected_operation_id,
            claim_digest=claim_digest,
        )
    if verify_existing:
        raise ValueError("execution bundle verification requires an existing destination")
    if archive is None:
        raise ValueError("execution bundle archive is required for fresh extraction")
    observed_digest = _archive_digest(archive)
    if observed_digest != expected_digest:
        raise ValueError("execution bundle digest differs")

    temporary = destination.with_name(f".{destination.name}.extract-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("execution bundle temporary destination already exists")
    temporary.mkdir(mode=0o700)
    published = False
    try:
        manifest, files = _extract(archive, temporary)
        _validate_manifest(manifest, expected_operation_id, files)
        _apply_modes(temporary, manifest)
        result = _receipt(
            bundle_digest=observed_digest,
            operation_id=expected_operation_id,
            claim_digest=claim_digest,
            files=files,
            inventory_digest=_manifest_inventory_digest(manifest),
        )
        write_private_bytes(
            temporary / _RETAINED_MANIFEST,
            canonical_bytes(manifest),
        )
        write_private_bytes(temporary / _RECEIPT, canonical_bytes(result))
        _sync_tree_directories(temporary)
        os.rename(temporary, destination)
        _sync_directory(destination.parent)
        published = True
        return result
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_tree_directories(root: Path) -> None:
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in (*directories, root):
        if directory.is_symlink():
            raise ValueError("execution bundle extracted directory is a link")
        _sync_directory(directory)


def _extract(archive: Path, destination: Path) -> tuple[dict[str, object], dict[str, str]]:
    manifest: dict[str, object] | None = None
    files: dict[str, str] = {}
    total_bytes = 0
    try:
        with tarfile.open(archive, mode="r:gz") as stream:
            payload_count = 0
            member_count = 0
            for member in stream:
                member_count += 1
                if member_count > _MAX_MEMBERS + 1:
                    raise ValueError("execution bundle archive member count exceeds its limit")
                relative = _member_path(member.name)
                if member.isdir():
                    continue
                if not member.isfile() or member.size > _MAX_FILE_BYTES:
                    raise ValueError("execution bundle member type or size is invalid")
                source = stream.extractfile(member)
                if source is None:
                    raise ValueError("execution bundle member is unreadable")
                if relative == "manifest.json":
                    if manifest is not None or member.size > 4 * 1024 * 1024:
                        raise ValueError("execution bundle manifest is invalid")
                    payload = source.read(member.size + 1)
                    if len(payload) != member.size:
                        raise ValueError("execution bundle manifest size differs")
                    value = json.loads(payload)
                    if not isinstance(value, dict):
                        raise ValueError("execution bundle manifest is invalid")
                    manifest = value
                    continue
                total_bytes += member.size
                if total_bytes > _MAX_TOTAL_BYTES:
                    raise ValueError("execution bundle exceeds its total size limit")
                payload_count += 1
                if payload_count > _MAX_MEMBERS:
                    raise ValueError("execution bundle member count exceeds its limit")
                if relative in files:
                    raise ValueError("execution bundle repeats a file")
                target = destination.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                digest = hashlib.sha256()
                copied = 0
                with source, os.fdopen(descriptor, "wb") as output:
                    while chunk := source.read(1024 * 1024):
                        copied += len(chunk)
                        if copied > member.size:
                            raise ValueError("execution bundle member exceeded its declared size")
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if copied != member.size:
                    raise ValueError("execution bundle member size differs")
                files[relative] = digest.hexdigest()
    except (tarfile.TarError, EOFError, json.JSONDecodeError) as exc:
        raise ValueError("execution bundle archive is invalid") from exc
    if manifest is None or not files:
        raise ValueError("execution bundle manifest or payload is missing")
    return manifest, dict(sorted(files.items()))


def _member_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or not path.parts
        or path.parts[0] != _ROOT
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("execution bundle path is invalid")
    relative = PurePosixPath(*path.parts[1:]).as_posix()
    if not relative or relative == _RECEIPT:
        raise ValueError("execution bundle path is invalid")
    return relative


def _validate_manifest(
    manifest: dict[str, object], operation_id: str, files: dict[str, str]
) -> None:
    declared = manifest.get("files")
    if (
        set(manifest) != {"schema_version", "operation_id", "files"}
        or manifest.get("schema_version") != "fdai.execution-bundle-manifest.v1"
        or manifest.get("operation_id") != operation_id
        or not isinstance(declared, dict)
        or set(declared) != set(files)
    ):
        raise ValueError("execution bundle manifest differs from extracted payload")
    for relative, digest in files.items():
        record = declared.get(relative)
        if (
            not isinstance(record, dict)
            or set(record) != {"sha256", "mode"}
            or record.get("sha256") != digest
            or record.get("mode") not in {"0600", "0700"}
        ):
            raise ValueError("execution bundle manifest differs from extracted payload")


def _receipt(
    *,
    bundle_digest: str,
    operation_id: str,
    claim_digest: str,
    files: dict[str, str],
    inventory_digest: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "fdai.run-command-bundle-host-result.v1",
        "state": "verified",
        "operation_id": operation_id,
        "bundle_digest": bundle_digest,
        "claim_digest": claim_digest,
        "file_count": len(files),
        "inventory_digest": inventory_digest,
        "mutation_performed": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result


def _verify_existing(
    destination: Path,
    *,
    bundle_digest: str,
    operation_id: str,
    claim_digest: str,
) -> dict[str, object]:
    receipt = json.loads(read_private_bytes(destination / _RECEIPT, max_bytes=16_384))
    if not isinstance(receipt, dict):
        raise ValueError("execution bundle retained receipt is invalid")
    manifest = json.loads(
        read_private_bytes(destination / _RETAINED_MANIFEST, max_bytes=4 * 1024 * 1024)
    )
    if not isinstance(manifest, dict):
        raise ValueError("execution bundle retained manifest is invalid")
    files = _destination_files(destination, manifest)
    _validate_manifest(manifest, operation_id, files)
    expected = _receipt(
        bundle_digest=bundle_digest,
        operation_id=operation_id,
        claim_digest=claim_digest,
        files=files,
        inventory_digest=_manifest_inventory_digest(manifest),
    )
    if receipt != expected:
        raise ValueError("execution bundle retained destination differs")
    return expected


def _destination_files(destination: Path, manifest: dict[str, object]) -> dict[str, str]:
    root_details = destination.lstat()
    if (
        destination.is_symlink()
        or not stat.S_ISDIR(root_details.st_mode)
        or stat.S_IMODE(root_details.st_mode) != 0o700
        or root_details.st_uid != os.geteuid()
    ):
        raise ValueError("execution bundle retained destination is invalid")
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        raise ValueError("execution bundle manifest is invalid")
    files: dict[str, str] = {}
    total_bytes = 0
    for directory, directories, names in os.walk(destination, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in directories):
            raise ValueError("execution bundle retained destination contains a link")
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(destination).as_posix()
            if relative in {_RECEIPT, _RETAINED_MANIFEST}:
                continue
            if len(files) >= _MAX_MEMBERS:
                raise ValueError("execution bundle retained destination exceeds its file limit")
            details = candidate.lstat()
            record = declared.get(relative)
            if (
                candidate.is_symlink()
                or not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or not isinstance(record, dict)
                or record.get("mode") not in {"0600", "0700"}
                or stat.S_IMODE(details.st_mode) != int(str(record["mode"]), 8)
                or details.st_size > _MAX_FILE_BYTES
            ):
                raise ValueError("execution bundle retained destination is invalid")
            total_bytes += details.st_size
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ValueError("execution bundle retained destination exceeds its size limit")
            descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                copied = 0
                while chunk := stream.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > details.st_size:
                        raise ValueError("execution bundle retained file grew")
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            if (
                copied != details.st_size
                or opened.st_ino != details.st_ino
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
            ):
                raise ValueError("execution bundle retained file changed")
            files[relative] = digest.hexdigest()
    return dict(sorted(files.items()))


def _apply_modes(destination: Path, manifest: dict[str, object]) -> None:
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        raise ValueError("execution bundle manifest is invalid")
    for relative, value in declared.items():
        if not isinstance(relative, str) or not isinstance(value, dict):
            raise ValueError("execution bundle manifest is invalid")
        mode = value.get("mode")
        if mode not in {"0600", "0700"}:
            raise ValueError("execution bundle manifest mode is invalid")
        path = destination.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError("execution bundle manifest file is invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            os.fchmod(descriptor, int(mode, 8))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _manifest_inventory_digest(manifest: dict[str, object]) -> str:
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        raise ValueError("execution bundle manifest is invalid")
    return canonical_digest({"files": declared})


def _archive_digest(path: Path) -> str:
    details = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(details.st_mode)
        or not 0 < details.st_size <= _MAX_ARCHIVE_BYTES
    ):
        raise ValueError("execution bundle archive type or size is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (
        opened.st_ino != details.st_ino
        or opened.st_size != details.st_size
        or after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
    ):
        raise ValueError("execution bundle archive changed while being read")
    return digest.hexdigest()


def main(arguments: Sequence[str] | None = None) -> int:
    """Receive one fixed execution bundle and emit a bounded machine result."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--bundle-digest", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--claim-digest", required=True)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(arguments)
    try:
        result = receive_execution_bundle(
            args.archive,
            args.destination,
            expected_digest=args.bundle_digest,
            expected_operation_id=args.operation_id,
            claim_digest=args.claim_digest,
            verify_existing=args.verify_existing,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        print("run command receiver failed; preserve retained evidence", file=sys.stderr)
        return 3
    print(canonical_bytes(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
