"""Prove the pre-host Foundation root plans locally without Azure backend access."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_foundation_backend_supports_a_fresh_local_saved_plan(tmp_path):
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("real Terraform is unavailable; structural backend tests remain mandatory")
    source = (ROOT / "infra/genesis-foundation/versions.tf").read_text()
    backend = re.search(r'backend\s+"[^"]+"\s*\{[^}]*\}', source)
    (tmp_path / "main.tf").write_text(
        "terraform {\n" + (backend.group(0) if backend else "") + "\n}\n"
    )
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "TF_DATA_DIR": str(tmp_path / "data"),
        "TF_IN_AUTOMATION": "1",
        "CHECKPOINT_DISABLE": "1",
    }
    for arguments in (
        ["init", "-backend=false", "-input=false"],
        ["plan", "-input=false", "-no-color", "-out=plan.tfplan"],
    ):
        result = subprocess.run(  # noqa: S603 - provider-free local Terraform only.
            [terraform, *arguments],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "plan.tfplan").is_file()


def test_remote_backend_is_only_an_explicit_migration_input():
    source = (ROOT / "infra/genesis-foundation/versions.tf").read_text()
    assert 'backend "azurerm"' not in source
    example = ROOT / "infra/genesis-foundation/backend.azurerm.tf.example"
    assert example.read_text() == 'terraform {\n  backend "azurerm" {}\n}\n'
