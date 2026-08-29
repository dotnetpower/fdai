from __future__ import annotations

import importlib.util
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
