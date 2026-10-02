"""Runner-image re-verification tolerates only tenant patch-orchestration drift."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_runner_image as command  # noqa: E402
from genesis_runner_image_policy_drift import tenant_patch_policy_drift  # noqa: E402

_OBSERVED = {
    "name": "vm-runner-verify",
    "size": "Standard_D2as_v5",
    "patch_mode": "AutomaticByPlatform",
    "patch_assessment_mode": "ImageDefault",
    "bypass_platform_safety_checks_on_user_schedule_enabled": True,
}


def _vm_update(
    address: str = "azurerm_linux_virtual_machine.verifier",
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actions: list[str] | None = None,
    after_unknown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed = dict(_OBSERVED if before is None else before)
    planned = (
        {**observed, "bypass_platform_safety_checks_on_user_schedule_enabled": False}
        if after is None
        else after
    )
    return {
        "address": address,
        "mode": "managed",
        "type": "azurerm_linux_virtual_machine",
        "change": {
            "actions": actions or ["update"],
            "before": observed,
            "after": planned,
            "after_unknown": after_unknown or {},
        },
    }


def _data_read() -> dict[str, Any]:
    return {
        "address": "data.azapi_resource.runner_image",
        "mode": "data",
        "change": {"actions": ["read"], "before": None, "after": {}, "after_unknown": {}},
    }


def _no_op(address: str) -> dict[str, Any]:
    return {
        "address": address,
        "mode": "managed",
        "change": {"actions": ["no-op"], "before": {}, "after": {}, "after_unknown": {}},
    }


def test_patch_policy_drift_on_the_deallocated_vms_is_tolerated() -> None:
    plan = {
        "resource_changes": [
            _no_op("azurerm_image.runner"),
            _vm_update(),
            _vm_update(
                "azurerm_linux_virtual_machine.builder",
                after={
                    **_OBSERVED,
                    "patch_mode": "ImageDefault",
                    "bypass_platform_safety_checks_on_user_schedule_enabled": False,
                },
            ),
            _data_read(),
        ]
    }

    assert tenant_patch_policy_drift(plan) == (
        "azurerm_linux_virtual_machine.builder",
        "azurerm_linux_virtual_machine.verifier",
    )


@pytest.mark.parametrize(
    "change",
    [
        _vm_update(
            after={
                **_OBSERVED,
                "size": "Standard_D4as_v5",
                "bypass_platform_safety_checks_on_user_schedule_enabled": False,
            }
        ),
        _vm_update(after_unknown={"os_disk": [{"disk_size_gb": True}]}),
        _vm_update("azurerm_linux_virtual_machine.runner"),
        _vm_update(actions=["delete", "create"]),
        _vm_update(before={**_OBSERVED, "patch_mode": "ImageDefault"}),
        _vm_update(before={**_OBSERVED, "patch_mode": "Manual"}),
        _vm_update(before={**_OBSERVED, "patch_assessment_mode": "Manual"}),
        _vm_update(after=dict(_OBSERVED)),
        {
            "address": "azurerm_image.runner",
            "mode": "managed",
            "change": {
                "actions": ["update"],
                "before": {},
                "after": {"tags": {}},
                "after_unknown": {},
            },
        },
        {
            "address": "azurerm_firewall.egress",
            "mode": "managed",
            "change": {"actions": ["create"], "before": None, "after": {}, "after_unknown": {}},
        },
        {"address": "azurerm_linux_virtual_machine.verifier", "mode": "managed"},
    ],
)
def test_any_other_planned_change_fails_closed(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="zero-change"):
        tenant_patch_policy_drift({"resource_changes": [change, _data_read()]})


@pytest.mark.parametrize("plan", [{}, {"resource_changes": "none"}, {"resource_changes": []}])
def test_malformed_or_empty_projection_fails_closed(plan: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="zero-change"):
        tenant_patch_policy_drift(plan)


def _fake_terraform(
    monkeypatch: pytest.MonkeyPatch, *, plan_exit: int, projection: object
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command_line: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(command_line))
        if command_line[1] == "plan":
            output = next(item for item in command_line if item.startswith("-out="))
            Path(output.removeprefix("-out=")).write_bytes(b"plan")
            return subprocess.CompletedProcess(command_line, plan_exit, "", "")
        return subprocess.CompletedProcess(command_line, 0, json.dumps(projection), "")

    monkeypatch.setattr(command, "run_with_heartbeat", run)
    return calls


def test_zero_change_verification_accepts_tolerated_drift_and_removes_its_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_terraform(
        monkeypatch,
        plan_exit=2,
        projection={"resource_changes": [_vm_update(), _data_read()]},
    )

    command._verify_zero_change(work_dir=tmp_path, terraform=tmp_path / "terraform", environment={})

    assert [call[1] for call in calls] == ["plan", "show"]
    assert not (tmp_path / "runner-image-zero-change.tfplan").exists()


def test_zero_change_verification_rejects_other_drift_and_removes_its_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_terraform(
        monkeypatch,
        plan_exit=2,
        projection={"resource_changes": [_vm_update(actions=["delete", "create"])]},
    )

    with pytest.raises(ValueError, match="zero-change"):
        command._verify_zero_change(
            work_dir=tmp_path, terraform=tmp_path / "terraform", environment={}
        )
    assert not (tmp_path / "runner-image-zero-change.tfplan").exists()


def test_zero_change_verification_without_drift_skips_the_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_terraform(monkeypatch, plan_exit=0, projection={})

    command._verify_zero_change(work_dir=tmp_path, terraform=tmp_path / "terraform", environment={})

    assert [call[1] for call in calls] == ["plan"]
