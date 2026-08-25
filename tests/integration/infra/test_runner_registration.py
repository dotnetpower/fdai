"""Private deployment runner registration contract tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def test_registration_replaces_existing_local_configuration() -> None:
    bootstrap_root = Path(__file__).resolve().parents[3] / "infra" / "bootstrap"
    script_path = bootstrap_root / "register-runner.sh"
    remote_script_path = bootstrap_root / "register-runner-remote.sh"
    script = script_path.read_text(encoding="utf-8")
    remote_script = remote_script_path.read_text(encoding="utf-8")

    subprocess.run(  # noqa: S603 - static repository-owned script
        ["/usr/bin/bash", "-n", str(script_path)],
        check=True,
    )
    subprocess.run(  # noqa: S603 - static repository-owned script
        ["/usr/bin/bash", "-n", str(remote_script_path)],
        check=True,
    )
    assert 'actions/runners/remove-token" --jq .token' in script
    assert "if [[ -f .runner ]]; then" in remote_script
    assert remote_script.index("./svc.sh uninstall") < remote_script.index(
        "./config.sh remove --token"
    )
    assert remote_script.index("./config.sh remove --token") < remote_script.index(
        "./config.sh --unattended"
    )
    assert "config.sh remove --unattended" not in remote_script
    assert "FDAI_RUNNER_REGISTRATION_OK" in remote_script
    assert 'grep -Fq "FDAI_RUNNER_REGISTRATION_OK slots=${PARALLELISM}"' in script


def test_registration_supports_bounded_parallel_runner_slots() -> None:
    bootstrap_root = Path(__file__).resolve().parents[3] / "infra" / "bootstrap"
    script_path = bootstrap_root / "register-runner.sh"
    script = script_path.read_text(encoding="utf-8")
    remote_script = (bootstrap_root / "register-runner-remote.sh").read_text(encoding="utf-8")
    variables = (bootstrap_root / "variables.tf").read_text(encoding="utf-8")
    main = (bootstrap_root / "main.tf").read_text(encoding="utf-8")
    cloud_init = (bootstrap_root / "runner-cloud-init.yaml.tftpl").read_text(encoding="utf-8")

    assert 'PARALLELISM="${5:-1}"' in script
    assert '[[ ! "$PARALLELISM" =~ ^[1-5]$ ]]' in script
    assert "base64 -d | bash -s --" in script
    assert 'for slot in $(seq 1 "$PARALLELISM")' in remote_script
    assert 'runner_home="$BASE_HOME-$slot"' in remote_script
    assert 'runner_name="$(hostname)-$slot"' in remote_script
    assert 'for runner_home in "$BASE_HOME"-[2-5]' in remote_script
    assert 'variable "runner_parallelism"' in variables
    assert "var.runner_parallelism >= 1 && var.runner_parallelism <= 5" in variables
    assert "runner_parallelism = var.runner_parallelism" in main
    assert 'RUNNER_PARALLELISM="${runner_parallelism}"' in cloud_init
    assert 'runner_home="$RUNNER_BASE_HOME-$slot"' in cloud_init
    assert 'runner_name="$(hostname)-$slot"' in cloud_init


def test_runner_uses_sustained_compute_and_an_ephemeral_resource_disk() -> None:
    bootstrap_root = Path(__file__).resolve().parents[3] / "infra" / "bootstrap"
    variables = (bootstrap_root / "variables.tf").read_text(encoding="utf-8")
    main = (bootstrap_root / "main.tf").read_text(encoding="utf-8")

    assert 'default     = "Standard_D4ds_v5"' in variables
    assert 'storage_account_type = "Standard_LRS"' in main
    assert 'option    = "Local"' in main
    assert 'placement = "ResourceDisk"' in main
    assert 'condition     = var.runner_auto_shutdown_time == ""' in main


def _run_storage_posture_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vm_payload: str,
) -> subprocess.CompletedProcess[str]:
    bootstrap_root = Path(__file__).resolve().parents[3] / "infra" / "bootstrap"
    script_path = bootstrap_root / "check-runner-storage-posture.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_az = fake_bin / "az"
    fake_az.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "account show")
    if [[ "$*" == *"[id,tenantId]"* ]]; then
      printf '%s\\n%s\\n' "$TEST_SUBSCRIPTION" "$TEST_TENANT"
    else
      printf '%s\\n' "$TEST_TENANT"
    fi
    ;;
  "account set") ;;
  "vm show") printf '%s\\n' "$TEST_VM_PAYLOAD" ;;
  *) exit 64 ;;
esac
""",
        encoding="utf-8",
    )
    fake_az.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("TEST_SUBSCRIPTION", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("TEST_TENANT", "00000000-0000-0000-0000-000000000002")
    monkeypatch.setenv("TEST_VM_PAYLOAD", vm_payload)

    return subprocess.run(  # noqa: S603 - static repository-owned script
        [
            "/usr/bin/bash",
            str(script_path),
            os.environ["TEST_SUBSCRIPTION"],
            os.environ["TEST_TENANT"],
            "rg-example-ops",
            "vm-runner-example",
            "Standard_D4ds_v5",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_storage_posture_check_accepts_local_ephemeral_os_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_storage_posture_check(
        tmp_path,
        monkeypatch,
        '{"vm_size":"Standard_D4ds_v5","option":"Local","placement":"ResourceDisk","managed_disk_id":null}',
    )

    assert result.returncode == 0, result.stderr
    assert "FDAI_RUNNER_STORAGE_POSTURE_OK" in result.stdout


def test_storage_posture_check_rejects_managed_os_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_storage_posture_check(
        tmp_path,
        monkeypatch,
        '{"vm_size":"Standard_D4ds_v5","option":null,"placement":null,"managed_disk_id":"/example/disk"}',
    )

    assert result.returncode == 1
    assert "runner storage posture drift detected" in result.stderr
    assert "a managed OS disk exists" in result.stderr
    assert "blue/green bootstrap procedure" in result.stderr
