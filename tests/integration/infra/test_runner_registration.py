"""Private deployment runner registration contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_registration_replaces_existing_local_configuration() -> None:
    script_path = Path(__file__).resolve().parents[3] / "infra" / "bootstrap" / "register-runner.sh"
    script = script_path.read_text(encoding="utf-8")

    subprocess.run(  # noqa: S603 - static repository-owned script
        ["/usr/bin/bash", "-n", str(script_path)],
        check=True,
    )
    assert 'actions/runners/remove-token" --jq .token' in script
    assert "if [ -f .runner ]; then" in script
    assert script.index("./svc.sh uninstall") < script.index("./config.sh remove --token")
    assert script.index("./config.sh remove --token") < script.index("./config.sh --unattended")
    assert "config.sh remove --unattended" not in script


def test_registration_supports_bounded_parallel_runner_slots() -> None:
    bootstrap_root = Path(__file__).resolve().parents[3] / "infra" / "bootstrap"
    script_path = bootstrap_root / "register-runner.sh"
    script = script_path.read_text(encoding="utf-8")
    variables = (bootstrap_root / "variables.tf").read_text(encoding="utf-8")
    main = (bootstrap_root / "main.tf").read_text(encoding="utf-8")
    cloud_init = (bootstrap_root / "runner-cloud-init.yaml.tftpl").read_text(encoding="utf-8")

    assert 'PARALLELISM="${5:-1}"' in script
    assert '[[ ! "$PARALLELISM" =~ ^[1-5]$ ]]' in script
    assert r"for slot in \$(seq 1 ${PARALLELISM})" in script
    assert r"runner_home=\"\$base_home-\$slot\"" in script
    assert r"runner_name=\"\$(hostname)-\$slot\"" in script
    assert r"for runner_home in \"\$base_home\"-[2-5]" in script
    assert 'variable "runner_parallelism"' in variables
    assert "var.runner_parallelism >= 1 && var.runner_parallelism <= 5" in variables
    assert "runner_parallelism = var.runner_parallelism" in main
    assert 'RUNNER_PARALLELISM="${runner_parallelism}"' in cloud_init
    assert 'runner_home="$RUNNER_BASE_HOME-$slot"' in cloud_init
    assert 'runner_name="$(hostname)-$slot"' in cloud_init
