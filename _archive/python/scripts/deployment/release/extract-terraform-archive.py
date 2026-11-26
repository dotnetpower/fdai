#!/usr/bin/env python3
"""Extract the pinned Terraform binary through a bounded private-file boundary."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import zipfile
from pathlib import Path

_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_LICENSE_BYTES = 64 * 1024
_MAX_BINARY_BYTES = 256 * 1024 * 1024
_CHUNK = 1024 * 1024


class TerraformArchiveError(RuntimeError):
    """The pinned Terraform archive is malformed or unsafe to extract."""


def extract_terraform_archive(archive_path: Path, output_path: Path) -> int:
    """Extract one verified Terraform executable without following or replacing links.

    The caller verifies the archive SHA-256 before this function runs. This boundary
    independently checks the official two-member ZIP shape, bounds decompression, and
    publishes the executable only into a current-UID mode-0700 directory. It returns
    the extracted byte count and removes a partial output after any failure.
    """

    if not archive_path.is_absolute() or not output_path.is_absolute():
        raise TerraformArchiveError("archive and output paths must be absolute")
    archive_descriptor = _open_archive(archive_path)
    parent_descriptor = -1
    try:
        parent_descriptor = _open_private_parent(output_path)
        with os.fdopen(archive_descriptor, "rb") as source:
            archive_descriptor = -1
            with zipfile.ZipFile(source, mode="r") as archive:
                members = _validated_members(archive)
                return _extract_binary(
                    archive,
                    members["terraform"],
                    output_path.name,
                    parent_descriptor,
                )
    finally:
        if archive_descriptor >= 0:
            os.close(archive_descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _open_archive(path: Path) -> int:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise TerraformArchiveError("archive is unavailable") from exc
    try:
        details = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or not 0 < details.st_size <= _MAX_ARCHIVE_BYTES
    ):
        os.close(descriptor)
        raise TerraformArchiveError("archive must be a bounded single-link regular file")
    return descriptor


def _open_private_parent(path: Path) -> int:
    if path.name in {"", ".", ".."}:
        raise TerraformArchiveError("output filename is invalid")
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TerraformArchiveError("output directory is unavailable") from exc
    try:
        details = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
        os.close(descriptor)
        raise TerraformArchiveError("output directory must be current-UID mode 0700")
    return descriptor


def _validated_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members = archive.infolist()
    names = [member.filename for member in members]
    expected = {
        "LICENSE.txt": (0o100644, _MAX_LICENSE_BYTES),
        "terraform": (0o100755, _MAX_BINARY_BYTES),
    }
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise TerraformArchiveError("archive member set is invalid")
    result: dict[str, zipfile.ZipInfo] = {}
    for member in members:
        expected_mode, maximum = expected[member.filename]
        mode = member.external_attr >> 16
        if (
            member.create_system != 3
            or mode != expected_mode
            or member.is_dir()
            or member.compress_type != zipfile.ZIP_DEFLATED
            or member.flag_bits & 0x1
            or not 0 < member.file_size <= maximum
            or not 0 < member.compress_size <= _MAX_ARCHIVE_BYTES
        ):
            raise TerraformArchiveError("archive member metadata is invalid")
        result[member.filename] = member
    return result


def _extract_binary(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    output_name: str,
    parent_descriptor: int,
) -> int:
    try:
        descriptor = os.open(
            output_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o700,
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        raise TerraformArchiveError("exclusive output creation failed") from exc
    try:
        with os.fdopen(descriptor, "wb") as target, archive.open(member, mode="r") as source:
            total = 0
            for chunk in iter(lambda: source.read(_CHUNK), b""):
                total += len(chunk)
                if total > member.file_size or total > _MAX_BINARY_BYTES:
                    raise TerraformArchiveError("extracted binary exceeds its bound")
                target.write(chunk)
            if total != member.file_size:
                raise TerraformArchiveError("extracted binary size does not match")
            target.flush()
            os.fchmod(target.fileno(), 0o755)
            os.fsync(target.fileno())
        return total
    except BaseException:
        try:
            os.unlink(output_name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    """Run the bounded release-only extractor with sanitized failure output."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        extract_terraform_archive(args.archive, args.output)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        print("terraform archive extraction failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
