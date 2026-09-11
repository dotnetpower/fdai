#!/usr/bin/env python3
"""Build the bounded private archive consumed by Foundation state migration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes

_MAX_FILES = 4096
_MAX_BYTES = 1024 * 1024 * 1024


def create_foundation_state_archive(
    *,
    terraform_root: Path,
    provider_mirror: Path,
    variables_file: Path,
    destination: Path,
    source_commit: str,
    expected_state_digest: str,
) -> dict[str, object]:
    """Create one link-free deterministic archive and return its exact digests."""

    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Foundation state handoff archive already exists")
    with TemporaryDirectory(prefix="foundation-state-archive-", dir=destination.parent) as raw:
        stage = Path(raw)
        stage.chmod(0o700)
        _copy_tree(terraform_root, stage / "root", exclude_state_backup=True)
        _copy_tree(provider_mirror, stage / "mirror", exclude_state_backup=False)
        variables = read_private_bytes(variables_file, max_bytes=1_048_576)
        _write_bytes(stage / "variables.auto.tfvars.json", variables, executable=False)
        state = read_private_bytes(stage / "root/terraform.tfstate", max_bytes=64 * 1024 * 1024)
        if hashlib.sha256(state).hexdigest() != expected_state_digest:
            raise ValueError("Foundation recovery state does not match the apply receipt")
        files = _file_manifest(stage)
        manifest: dict[str, object] = {
            "schema_version": "fdai.genesis-foundation-state-archive.v1",
            "source_commit": source_commit,
            "state_digest": expected_state_digest,
            "files": files,
        }
        manifest["manifest_digest"] = canonical_digest(manifest)
        _write_bytes(
            stage / "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n",
            executable=False,
        )
        _write_archive(stage, destination)
    archive_digest = _digest_file(destination)
    return {
        "schema_version": "fdai.genesis-foundation-state-archive-result.v1",
        "archive_digest": archive_digest,
        "manifest_digest": manifest["manifest_digest"],
        "state_digest": expected_state_digest,
        "file_count": len(files),
        "archive_size": destination.stat().st_size,
    }


def _copy_tree(source: Path, destination: Path, *, exclude_state_backup: bool) -> None:
    source_details = source.lstat()
    if not stat.S_ISDIR(source_details.st_mode):
        raise ValueError("Foundation state archive source must be a directory")
    destination.mkdir(mode=0o700)
    count = 0
    total = 0
    for entry in sorted(source.rglob("*")):
        relative = entry.relative_to(source)
        if ".terraform" in relative.parts:
            continue
        if exclude_state_backup and entry.name.startswith("terraform.tfstate.backup"):
            continue
        details = entry.lstat()
        target = destination / relative
        if stat.S_ISDIR(details.st_mode):
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation state archive source contains an unsafe file")
        count += 1
        total += details.st_size
        if count > _MAX_FILES or total > _MAX_BYTES:
            raise ValueError("Foundation state archive source exceeds its bounds")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        executable = bool(details.st_mode & 0o111)
        _write_bytes(target, entry.read_bytes(), executable=executable)


def _file_manifest(stage: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    total = 0
    for path in sorted(stage.rglob("*")):
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation state archive stage contains an unsafe file")
        total += details.st_size
        if len(result) >= _MAX_FILES or total > _MAX_BYTES:
            raise ValueError("Foundation state archive stage exceeds its bounds")
        result[path.relative_to(stage).as_posix()] = {
            "sha256": _digest_file(path),
            "executable": bool(details.st_mode & 0o111),
        }
    if not result:
        raise ValueError("Foundation state archive cannot be empty")
    return result


def _write_archive(stage: Path, destination: Path) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with (
        os.fdopen(descriptor, "wb") as stream,
        tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.PAX_FORMAT) as bundle,
    ):
        for path in sorted(stage.rglob("*")):
            relative = path.relative_to(stage).as_posix()
            details = path.lstat()
            info = tarfile.TarInfo(relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            if stat.S_ISDIR(details.st_mode):
                info.type = tarfile.DIRTYPE
                info.mode = 0o700
                bundle.addfile(info)
                continue
            info.size = details.st_size
            info.mode = 0o700 if details.st_mode & 0o111 else 0o600
            with path.open("rb") as source:
                bundle.addfile(info, source)


def _write_bytes(path: Path, value: bytes, *, executable: bool) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o700 if executable else 0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
