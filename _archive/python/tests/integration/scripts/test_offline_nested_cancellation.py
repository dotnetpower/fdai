"""Cancel real nested release supervision without leaving a synthetic builder alive."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from tests.integration.scripts.test_offline_cli_build_environment import timed_function
from tests.integration.scripts.test_standalone_kit_release_guards import ROOT, executable


def test_outer_release_cancellation_reaches_nested_timeout_group(tmp_path):
    tools = tmp_path / "tools"
    pid_file = tmp_path / "builder-pid"
    executable(
        tools / "uv",
        '[[ "$1" == "build" ]] || exit 0\n'
        'exec "$TEST_PYTHON" -c \'import os, signal; '
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        'open(os.environ["TEST_PID"], "w").write(str(os.getpid())); signal.pause()\'\n',
    )
    stage = (ROOT / "scripts/deployment/release/stage-offline-kit.sh").read_text()
    body = stage.split("build_cli_wheels() {", 1)[1]
    functions = "build_cli_wheels() {" + body.split('echo "-- pinned release toolchain"', 1)[0]
    functions = timed_function() + functions
    child = tmp_path / "stage.sh"
    child.write_text("set -euo pipefail\n" + functions + "\nbuild_cli_wheels\n")
    try:
        result = subprocess.run(  # noqa: S603 - actual outer supervisor and staged shell helper.
            [
                sys.executable,
                str(ROOT / "scripts/automation/run-bounded-command.py"),
                "--label",
                "cancel-kit",
                "--timeout-seconds",
                "8",
                "--no-progress-seconds",
                "1",
                "--",
                "/bin/bash",
                str(child),
            ],
            env={
                **os.environ,
                "PATH": f"{tools}:/usr/bin:/bin",
                "OUT": str(tmp_path),
                "repo_root": str(ROOT),
                "PYTHON": sys.executable,
                "TEST_PYTHON": sys.executable,
                "TEST_PID": str(pid_file),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=12,
        )
        assert result.returncode == 124
        pid = int(pid_file.read_text())
        process = Path(f"/proc/{pid}/stat")
        assert not process.exists() or process.read_text().split()[2] == "Z"
    finally:
        if pid_file.exists():
            try:
                group = os.getpgid(int(pid_file.read_text()))
                if group != os.getpgrp():
                    os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
