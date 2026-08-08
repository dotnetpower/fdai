"""Private deployment runner registration contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_registration_replaces_existing_local_configuration() -> None:
    script_path = Path(__file__).resolve().parents[2] / "infra" / "bootstrap" / "register-runner.sh"
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
