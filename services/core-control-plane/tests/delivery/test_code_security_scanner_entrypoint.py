from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def test_scanner_entrypoint_maps_the_supervised_worker_command() -> None:
    root = Path(__file__).resolve().parents[4]
    entrypoint = (
        root / "services/core-control-plane/docker/code-security-scanner-entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert "serve-workers)\n    shift\n    run_with_scanners serve-workers" in entrypoint
    assert "serve-workers [ARGS...]" in entrypoint


def test_scanner_entrypoint_checks_worker_heartbeat_freshness(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    entrypoint = root / "services/core-control-plane/docker/code-security-scanner-entrypoint.sh"
    health_file = tmp_path / "worker.health"
    health_file.touch()
    environment = dict(os.environ, FDAI_CODE_SECURITY_HEALTH_FILE=str(health_file))

    fresh = subprocess.run(  # noqa: S603 - fixed repository-owned entrypoint.
        [str(entrypoint), "worker-health", "30"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fresh.returncode == 0

    stale_at = time.time() - 31
    os.utime(health_file, (stale_at, stale_at))
    stale = subprocess.run(  # noqa: S603 - fixed repository-owned entrypoint.
        [str(entrypoint), "worker-health", "30"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode == 1
