"""Private deployment runner registration contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
