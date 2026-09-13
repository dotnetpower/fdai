"""Keep discovered hardware aligned with Terraform and authenticated policy boundaries."""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_sku_selection import select_image_vm_inputs  # noqa: E402
from genesis_vm_sku_policy import parse_vm_policy  # noqa: E402
from genesis_vm_sku_preflight import POLICY_NAME  # noqa: E402
from tests.integration.scripts.test_genesis_runner_image import _inputs  # noqa: E402


def vm_block(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    match = re.search(
        rf'^resource "azurerm_linux_virtual_machine" "{name}" \{{\n(.*?)^\}}',
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match[1]


@pytest.mark.parametrize("role", ["builder", "verifier"])
def test_image_vm_policy_matches_actual_managed_os_disks(role):
    policy = parse_vm_policy((ROOT / "infra/genesis-runner-image" / POLICY_NAME).read_bytes())
    block = vm_block(ROOT / "infra/genesis-runner-image/main.tf", role)
    assert getattr(policy, role).disk_mode == "managed"
    assert re.search(rf"disk_size_gb\s*=\s*{policy.os_disk_gib}\s*$", block, re.MULTILINE)
    assert re.search(r'storage_account_type\s*=\s*"Standard_LRS"', block)
    assert "diff_disk_settings" not in block


def test_host_policy_matches_actual_resource_disk_placement():
    policy = parse_vm_policy((ROOT / "infra/genesis-runner-image" / POLICY_NAME).read_bytes())
    block = vm_block(ROOT / "infra/bootstrap/main.tf", "runner")
    assert policy.foundation.disk_mode == "resource-disk"
    assert "diff_disk_settings" in block
    assert re.search(r'option\s*=\s*"Local"', block)
    assert re.search(r'placement\s*=\s*"ResourceDisk"', block)


@pytest.mark.parametrize(
    ("fault", "error"),
    [("broken_link", OSError), ("public_mode", PermissionError), ("malformed", CheckError)],
)
def test_present_invalid_v2_policy_cannot_fall_back_to_legacy(tmp_path, fault, error):
    inputs, destination = _inputs(tmp_path)
    inputs = replace(inputs, foundation_vm_size="Standard_D4ds_v4")
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    legacy = root / "sku-policy.json"
    legacy.write_bytes((ROOT / "infra/genesis-runner-image/sku-policy.json").read_bytes())
    legacy.chmod(0o600)
    policy = root / POLICY_NAME
    if fault == "broken_link":
        policy.symlink_to(root / "absent.json")
    else:
        policy.write_bytes(
            b"{}"
            if fault == "malformed"
            else (ROOT / "infra/genesis-runner-image" / POLICY_NAME).read_bytes()
        )
        policy.chmod(0o644 if fault == "public_mode" else 0o600)
    before = destination.read_bytes()
    with pytest.raises(error):
        select_image_vm_inputs(
            inputs,
            terraform_root=root,
            destination=destination,
            azure_cli=Path("/usr/bin/az"),
            capture=lambda *_a, **_k: pytest.fail("No read or legacy fallback on invalid policy"),
            cwd=ROOT,
            environment={},
        )
    assert destination.read_bytes() == before
