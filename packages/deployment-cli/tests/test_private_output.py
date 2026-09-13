from __future__ import annotations

from pathlib import Path

import pytest

from fdai_deployment_cli.private_output import copy_private_file


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def test_copy_private_file_publishes_new_mode_0600_file(tmp_path: Path) -> None:
    private = _private_directory(tmp_path / "private")
    source = private / "source.bin"
    source.write_bytes(b"verified appliance")
    source.chmod(0o600)
    destination = private / "destination.bin"

    copied = copy_private_file(source, destination, max_bytes=1024)

    assert copied == len(b"verified appliance")
    assert destination.read_bytes() == b"verified appliance"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not list(private.glob(".destination.bin.copy-*"))


def test_copy_private_file_rejects_links_and_existing_destination(tmp_path: Path) -> None:
    private = _private_directory(tmp_path / "private")
    source = private / "source.bin"
    source.write_bytes(b"source")
    source.chmod(0o600)
    linked_source = private / "linked-source.bin"
    linked_source.symlink_to(source)
    target = private / "target.bin"
    target.write_bytes(b"unchanged")
    target.chmod(0o600)
    destination = private / "destination.bin"
    destination.symlink_to(target)

    with pytest.raises(OSError):
        copy_private_file(linked_source, private / "new.bin", max_bytes=1024)
    with pytest.raises(FileExistsError):
        copy_private_file(source, destination, max_bytes=1024)
    assert target.read_bytes() == b"unchanged"


def test_copy_private_file_removes_partial_destination_on_size_failure(tmp_path: Path) -> None:
    private = _private_directory(tmp_path / "private")
    source = private / "source.bin"
    source.write_bytes(b"too large")
    source.chmod(0o600)
    destination = private / "destination.bin"

    with pytest.raises(PermissionError, match="bounded regular file"):
        copy_private_file(source, destination, max_bytes=2)

    assert not destination.exists()
