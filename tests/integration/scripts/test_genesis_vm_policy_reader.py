"""Adversarial filesystem checks for source-authenticated VM policy reads."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_vm_sku_preflight import POLICY_NAME, load_vm_policy  # noqa: E402


def policy_file(tmp_path):
    path = tmp_path / "infra/genesis-runner-image" / POLICY_NAME
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / "infra/genesis-runner-image" / POLICY_NAME).read_bytes())
    return path


@pytest.mark.parametrize("fault", ["hardlink", "writable", "fifo", "symlink", "oversize"])
def test_policy_rejects_unsafe_file_identity(tmp_path, fault):
    path = policy_file(tmp_path)
    if fault == "hardlink":
        os.link(path, path.with_suffix(".link"))
    elif fault == "writable":
        path.chmod(0o666)
    elif fault == "oversize":
        path.write_bytes(path.read_bytes() + b" " * 16384)
    else:
        original = path.with_suffix(".original")
        path.rename(original)
        if fault == "fifo":
            os.mkfifo(path)
        else:
            path.symlink_to(original)
    with pytest.raises(CheckError, match="evidence_incomplete"):
        load_vm_policy(tmp_path)


def test_regular_policy_reader_preserves_exact_digest(tmp_path):
    path = policy_file(tmp_path)
    expected = load_vm_policy(ROOT)
    assert load_vm_policy(tmp_path) == expected
    assert path.is_file()
