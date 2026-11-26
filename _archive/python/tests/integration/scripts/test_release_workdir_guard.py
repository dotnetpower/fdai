from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/deployment/release/workdir-guard.py"
SPEC = importlib.util.spec_from_file_location("workdir_guard", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_workdir_guard_creates_and_verifies_private_sentinel(tmp_path: Path) -> None:
    workdir = tmp_path / "stage"
    MODULE.create_owned_workdir(workdir, sentinel=".owner", value="owned-v1")

    MODULE.verify_owned_workdir(workdir, sentinel=".owner", value="owned-v1")
    assert workdir.stat().st_mode & 0o777 == 0o700
    assert (workdir / ".owner").stat().st_mode & 0o777 == 0o600


def test_workdir_guard_rejects_public_or_linked_roots(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(MODULE.WorkdirGuardError, match="mode 0700"):
        MODULE.verify_owned_workdir(public, sentinel=".owner", value="owned-v1")

    private = tmp_path / "private"
    MODULE.create_owned_workdir(private, sentinel=".owner", value="owned-v1")
    linked = tmp_path / "linked"
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises(OSError):
        MODULE.verify_owned_workdir(linked, sentinel=".owner", value="owned-v1")


def test_workdir_guard_rejects_fifo_sentinel_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path / "stage"
    MODULE.create_owned_workdir(workdir, sentinel=".owner", value="owned-v1")
    sentinel = workdir / ".owner"
    sentinel.unlink()
    os.mkfifo(sentinel, mode=0o600)
    real_open = os.open

    def open_nonblocking(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == ".owner":
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_nonblocking)
    with pytest.raises(MODULE.WorkdirGuardError, match="sentinel is unsafe"):
        MODULE.verify_owned_workdir(workdir, sentinel=".owner", value="owned-v1")


def test_workdir_guard_rejects_replaceable_parent_chain(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)

    with pytest.raises(MODULE.WorkdirGuardError, match="parent chain is replaceable"):
        MODULE.create_owned_workdir(
            shared / "stage",
            sentinel=".owner",
            value="owned-v1",
        )

    shared.chmod(0o1777)
    MODULE.create_owned_workdir(
        shared / "stage",
        sentinel=".owner",
        value="owned-v1",
    )
    MODULE.verify_owned_workdir(
        shared / "stage",
        sentinel=".owner",
        value="owned-v1",
    )
