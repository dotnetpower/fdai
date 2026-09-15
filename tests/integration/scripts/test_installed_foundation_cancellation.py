"""Installed outer supervision must let Genesis terminate its nested effect group."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from fdai_deployment_cli.foundation_process import run_foundation_process

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("nested_stages", [1, 2, 3])
def test_installed_outer_deadline_gracefully_stops_nested_genesis(tmp_path, nested_stages):
    pid_file = tmp_path / "effect-pid"
    effect = (
        "import os, signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid())); signal.pause()"
    )
    stage = effect
    for _ in range(nested_stages):
        stage = (
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts/deployment/azure')!r})\n"
            "from genesis_subprocess import run_with_heartbeat\n"
            f"run_with_heartbeat((sys.executable, '-c', {stage!r}), "
            "cwd=Path.cwd(), timeout=20, capture_output=True)\n"
        )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_foundation_process(
                (sys.executable, "-c", stage), cwd=tmp_path, env=os.environ, timeout=1
            )
        if pid_file.exists():
            state = Path(f"/proc/{int(pid_file.read_text())}/stat")
            assert not state.exists() or state.read_text().split()[2] == "Z"
    finally:
        if pid_file.exists():
            try:
                group = os.getpgid(int(pid_file.read_text()))
                if group != os.getpgrp():
                    os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("status", [0, 2, 3])
def test_installed_supervisor_preserves_exit_status(tmp_path, status):
    result = run_foundation_process(
        (sys.executable, "-c", f"raise SystemExit({status})"),
        cwd=tmp_path,
        env=os.environ,
        timeout=5,
    )
    assert result.returncode == status
