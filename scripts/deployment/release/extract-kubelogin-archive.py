#!/usr/bin/env python3
"""Extract one verified kubelogin executable from its official ZIP archive."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_BINARY_BYTES = 256 * 1024 * 1024
_CHUNK = 1024 * 1024


class KubeloginArchiveError(RuntimeError):
    """The pinned kubelogin archive is malformed or unsafe to extract."""


def extract_kubelogin_archive(archive_path: Path, output_path: Path) -> int:
    """Extract the archive's sole regular file into a private directory."""

    if not archive_path.is_absolute() or not output_path.is_absolute():
        raise KubeloginArchiveError("archive and output paths must be absolute")
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    parent_descriptor = -1
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or not 0 < details.st_size <= _MAX_ARCHIVE_BYTES
        ):
            raise KubeloginArchiveError("archive must be a bounded regular file")
        parent_descriptor = os.open(
            output_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        parent_details = os.fstat(parent_descriptor)
        if parent_details.st_uid != os.geteuid() or stat.S_IMODE(parent_details.st_mode) != 0o700:
            raise KubeloginArchiveError("output directory must be current-UID mode 0700")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            with zipfile.ZipFile(source, mode="r") as archive:
                regular = []
                for member in archive.infolist():
                    path = PurePosixPath(member.filename)
                    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                        raise KubeloginArchiveError("archive member path is invalid")
                    mode = member.external_attr >> 16
                    if member.is_dir():
                        if not stat.S_ISDIR(mode):
                            raise KubeloginArchiveError("archive directory metadata is invalid")
                        continue
                    if (
                        not stat.S_ISREG(mode)
                        or member.flag_bits & 0x1
                        or not 0 < member.file_size <= _MAX_BINARY_BYTES
                        or not 0 < member.compress_size <= _MAX_ARCHIVE_BYTES
                    ):
                        raise KubeloginArchiveError("archive member metadata is invalid")
                    regular.append(member)
                if len(regular) != 1 or PurePosixPath(regular[0].filename).name != "kubelogin":
                    raise KubeloginArchiveError("archive member set is invalid")
                return _extract(archive, regular[0], output_path.name, parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _extract(
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
        raise KubeloginArchiveError("exclusive output creation failed") from exc
    try:
        with os.fdopen(descriptor, "wb") as target, archive.open(member, mode="r") as source:
            total = 0
            for chunk in iter(lambda: source.read(_CHUNK), b""):
                total += len(chunk)
                if total > member.file_size or total > _MAX_BINARY_BYTES:
                    raise KubeloginArchiveError("archive member exceeds its declared size")
                target.write(chunk)
            if total != member.file_size:
                raise KubeloginArchiveError("archive member size differs")
            target.flush()
            os.fsync(target.fileno())
            return total
    except BaseException:
        os.unlink(output_name, dir_fd=parent_descriptor)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        extract_kubelogin_archive(args.archive, args.output)
    except (OSError, zipfile.BadZipFile, KubeloginArchiveError):
        print("kubelogin archive extraction failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
