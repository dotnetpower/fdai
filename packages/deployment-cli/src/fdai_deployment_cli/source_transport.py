"""Transport verified source snapshots without release keys, archive paths or Git metadata."""

from __future__ import annotations

import hashlib
import argparse
import io
import json
import os
import re
import stat
import sys
import tarfile
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import BinaryIO

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.private_output import (
    _open_private_parent,
    read_private_bytes,
    write_private_bytes,
)
from fdai_deployment_cli.source_input import _read_tracked
from fdai_deployment_cli.source_snapshot import verify_source_snapshot

_MANIFEST = "source-input.json"
_MAX_FILE = 64 * 1024 * 1024
_MAX_TOTAL = 2 * 1024 * 1024 * 1024
_MAX_ARCHIVE = _MAX_TOTAL + 128 * 1024 * 1024
_MAX_MANIFEST = 16 * 1024 * 1024


def prepare_source_transport(
    snapshot: Path, work_dir: Path, *, snapshot_digest: str
) -> dict[str, object]:
    """Prepare or reverify an exact local source transfer without touching a remote host."""
    source = verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    archive = work_dir / "source-transfer.tar"
    receipt_path = work_dir / "source-transfer.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        receipt = load_json_object(
            read_private_bytes(receipt_path, max_bytes=16384), label="source transfer receipt"
        )
        digest = receipt.pop("receipt_digest", None)
        if (
            canonical_digest(receipt) != digest
            or receipt.get("snapshot_digest") != snapshot_digest
            or receipt.get("source_commit") != source["source_commit"]
        ):
            raise ValueError("source transfer receipt differs from current source")
        archive_digest = receipt.get("archive_digest")
        if not isinstance(archive_digest, str):
            raise ValueError("source transfer archive digest is unavailable")
    else:
        archive_digest = archive_source_snapshot(snapshot, archive, snapshot_digest=snapshot_digest)
        receipt = None
    with TemporaryDirectory(prefix=".source-transfer-verify-", dir=work_dir) as temporary:
        verified = receive_source_snapshot(
            archive,
            Path(temporary) / "snapshot",
            archive_digest=archive_digest,
            snapshot_digest=snapshot_digest,
        )
    result = {
        **verified,
        "archive_ref": archive.name,
        "state": "prepared",
        "remote_transfer_verified": False,
    }
    if receipt is not None and canonical_bytes(result) != canonical_bytes(receipt):
        raise ValueError("source transfer receipt differs from verified archive")
    result["receipt_digest"] = canonical_digest(result)
    if receipt is None:
        write_private_bytes(receipt_path, canonical_bytes(result))
    return result


def archive_source_snapshot(snapshot: Path, destination: Path, *, snapshot_digest: str) -> str:
    """Create a private deterministic source archive and return its independently retained hash.

    Every member is a regular numbered blob; symlink targets are data, never tar links.
    Existing archives are never replaced. Failed outputs remain for bounded inspection.
    """
    verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    manifest_bytes = read_private_bytes(snapshot / _MANIFEST, max_bytes=_MAX_MANIFEST)
    records = _records(manifest_bytes, snapshot_digest)
    parent = _open_private_parent(destination)
    try:
        descriptor = os.open(
            destination.name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "w+b") as output:
        with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            _add_blob(archive, _MANIFEST, manifest_bytes)
            total = 0
            for index, record in enumerate(records):
                content = _read_tracked(snapshot / "tree", record["path"], mode=record["mode"])
                total += len(content)
                if len(content) > _MAX_FILE or total > _MAX_TOTAL:
                    raise ValueError("source transport content exceeds its bound")
                if hashlib.sha256(content).hexdigest() != record["sha256"]:
                    raise ValueError("source transport content differs from its manifest")
                _add_blob(archive, f"blobs/{index:08d}", content)
        output.flush()
        os.fsync(output.fileno())
        verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
        return _digest(output)


def receive_source_snapshot(
    archive_path: Path,
    destination: Path,
    *,
    archive_digest: str,
    snapshot_digest: str,
    verify_existing: bool = False,
) -> dict[str, object]:
    """Verify the transferred bytes and recreate a fresh snapshot before any source execution.

    Both expected digests must arrive through the authenticated deployment handoff, not
    from the archive itself. No existing tree/state is adopted or deleted. Partial outputs
    remain on failure and cannot be resumed as verified. This does not authorize deployment.
    Verification-only recovery reads existing files without replacing or repairing them.
    """
    for digest in (archive_digest, snapshot_digest):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("source transport requires exact independent digests")
    parent = _open_private_parent(archive_path)
    try:
        descriptor = os.open(
            archive_path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent
        )
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_ARCHIVE
        ):
            raise ValueError("source transport requires a private bounded single-link archive")
        if _digest(source) != archive_digest:
            raise ValueError("source transport archive digest differs")
        source.seek(0)
        with (
            tarfile.open(fileobj=source, mode="r:") as archive,
            ThreadPoolExecutor(max_workers=4) as writer,
        ):
            manifest_bytes = _blob(archive, _MANIFEST, _MAX_MANIFEST)
            records = _records(manifest_bytes, snapshot_digest)
            tree = destination / "tree"
            if not verify_existing:
                parent = _open_private_parent(destination)
                try:
                    os.mkdir(destination.name, 0o700, dir_fd=parent)
                finally:
                    os.close(parent)
                tree.mkdir(mode=0o700)
                write_private_bytes(destination / _MANIFEST, manifest_bytes)
            links: list[tuple[Path, str]] = []
            pending: deque[Future[None]] = deque()
            total = 0
            for index, record in enumerate(records):
                content = _blob(archive, f"blobs/{index:08d}", _MAX_FILE)
                total += len(content)
                if total > _MAX_TOTAL or hashlib.sha256(content).hexdigest() != record["sha256"]:
                    raise ValueError("source transport blob differs or exceeds its bound")
                if verify_existing:
                    continue
                output = tree / record["path"]
                output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                for ancestor in output.parents:
                    if ancestor == tree:
                        break
                    ancestor.chmod(0o700)
                if record["mode"] == "120000":
                    target = os.fsdecode(content)
                    if not target or "\x00" in target or Path(target).is_absolute():
                        raise ValueError("source transport symlink target is invalid")
                    links.append((output, target))
                else:
                    pending.append(writer.submit(_restore_file, output, content, record["mode"]))
                    if len(pending) == 4:
                        pending.popleft().result()
            for completed in pending:
                completed.result()
            if archive.next() is not None:
                raise ValueError("source transport contains extra archive members")
            for output, target in links:
                output.symlink_to(target)
        after = os.fstat(source.fileno())
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or _digest(source) != archive_digest
        ):
            raise ValueError("source transport changed during reception")
    source_record = verify_source_snapshot(destination, expected_digest=snapshot_digest)
    return {
        "schema_version": "fdai.source-transport-receipt.v1",
        "source_commit": source_record["source_commit"],
        "archive_digest": archive_digest,
        "snapshot_digest": snapshot_digest,
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }


def _restore_file(output: Path, content: bytes, mode: str) -> None:
    write_private_bytes(output, content)
    if mode == "100755":
        output.chmod(0o700)


def _records(raw: bytes, expected_digest: str) -> list[dict[str, str]]:
    manifest = load_json_object(raw, label="source transport manifest", max_bytes=_MAX_MANIFEST)
    if canonical_digest(manifest) != expected_digest or canonical_bytes(manifest) != raw:
        raise ValueError("source transport manifest digest differs")
    if (
        set(manifest) != {"schema_version", "source", "files"}
        or manifest["schema_version"] != "fdai.source-snapshot.v1"
    ):
        raise ValueError("source transport manifest schema is invalid")
    source, records = manifest["source"], manifest["files"]
    if (
        not isinstance(source, dict)
        or source.get("provenance") != "operator-selected-source"
        or source.get("release_signature_verified") is not False
        or not isinstance(records, list)
        or not 1 <= len(records) <= 65536
        or type(source.get("file_count")) is not int
        or source["file_count"] != len(records)
        or canonical_digest({"files": records}) != source.get("content_digest")
    ):
        raise ValueError("source transport inventory is invalid")
    if (
        set(source)
        != {
            "schema_version",
            "provenance",
            "source_commit",
            "source_tree",
            "content_digest",
            "file_count",
            "release_signature_verified",
        }
        or source["schema_version"] != "fdai.source-deployment-input.v1"
        or not isinstance(source.get("source_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", source["source_commit"]) is None
        or not isinstance(source.get("source_tree"), str)
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source["source_tree"]) is None
    ):
        raise ValueError("source transport source identity is invalid")
    names: set[str] = set()
    result = []
    for record in records:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "mode", "sha256"}
            or not all(isinstance(value, str) for value in record.values())
        ):
            raise ValueError("source transport file record is invalid")
        path = PurePosixPath(record["path"])
        if (
            path.is_absolute()
            or path.as_posix() != record["path"]
            or ".." in path.parts
            or not path.parts
            or "\x00" in record["path"]
            or ".git" in path.parts
            or record["path"] in names
            or record["mode"] not in {"100644", "100755", "120000"}
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
        ):
            raise ValueError("source transport path or mode is invalid")
        names.add(record["path"])
        result.append(record)
    if any(parent.as_posix() in names for name in names for parent in PurePosixPath(name).parents):
        raise ValueError("source transport file and directory paths conflict")
    return result


def _add_blob(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size, member.mode = len(content), 0o600
    archive.addfile(member, io.BytesIO(content))


def _blob(archive: tarfile.TarFile, name: str, maximum: int) -> bytes:
    member = archive.next()
    if (
        member is None
        or member.name != name
        or not member.isfile()
        or member.pax_headers
        or not 0 <= member.size <= maximum
    ):
        raise ValueError("source transport archive member is invalid")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError("source transport blob is unavailable")
    with stream:
        content = stream.read(maximum + 1)
    if len(content) != member.size:
        raise ValueError("source transport blob is truncated")
    return content


def _digest(stream: BinaryIO) -> str:
    stream.seek(0)
    digest = hashlib.sha256()
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        if total > _MAX_ARCHIVE:
            raise ValueError("source transport archive exceeds its bound")
        digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Receive a source-only archive on an attested host without executing its contents."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive-digest", required=True)
    parser.add_argument("--snapshot-digest", required=True)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = receive_source_snapshot(
            args.archive,
            args.destination,
            archive_digest=args.archive_digest,
            snapshot_digest=args.snapshot_digest,
            verify_existing=args.verify_existing,
        )
    except (OSError, ValueError, tarfile.TarError):
        print(
            "source transport verification failed; preserve inputs and partial destination",
            file=sys.stderr,
        )
        return 3
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
