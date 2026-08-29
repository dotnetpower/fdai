from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/deployment/release/secure_work_file.py"
SPEC = importlib.util.spec_from_file_location("secure_work_file", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_work_file_is_created_exclusively_in_private_parent(tmp_path: Path) -> None:
    parent = tmp_path / "work"
    parent.mkdir(mode=0o700)
    output = parent / "output"

    MODULE.write_work_file(output, b"content", mode=0o600, replace=False)

    assert output.read_bytes() == b"content"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        MODULE.write_work_file(output, b"changed", mode=0o600, replace=False)


def test_work_file_replacement_never_follows_existing_symlink(tmp_path: Path) -> None:
    parent = tmp_path / "work"
    parent.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_bytes(b"unchanged")
    output = parent / "output"
    output.symlink_to(target)

    MODULE.write_work_file(output, b"replacement", mode=0o644, replace=True)

    assert target.read_bytes() == b"unchanged"
    assert output.read_bytes() == b"replacement"
    assert not output.is_symlink()


def test_work_file_rejects_fifo_race_and_public_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "work"
    parent.mkdir(mode=0o700)
    output = parent / "output"
    real_open = os.open

    def race_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == output.name:
            os.mkfifo(output)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", race_open)
    with pytest.raises(FileExistsError):
        MODULE.write_work_file(output, b"content", mode=0o600, replace=False)

    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(PermissionError, match="mode 0700"):
        MODULE.write_work_file(public / "output", b"content", mode=0o600, replace=False)
