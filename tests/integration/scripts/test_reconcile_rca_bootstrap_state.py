from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/azure/reconcile_rca_bootstrap_state.sh"
OLD = "module.measurement_runners[0].azurerm_container_app_job.baseline_regression"
NEW = "module.measurement_runners[0].azurerm_container_app_job.baseline_regression[0]"


def _run(tmp_path: Path, state: str) -> subprocess.CompletedProcess[str]:
    state_path = tmp_path / "state"
    state_path.write_text(state, encoding="utf-8")
    log_path = tmp_path / "moves"
    terraform = tmp_path / "terraform"
    terraform.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "state pull") cat "$STATE_PATH" ;;
  "state list") cat "$STATE_PATH" ;;
  "state mv")
    printf '%s -> %s\\n' "$3" "$4" >> "$MOVE_LOG"
    python3 - "$STATE_PATH" "$3" "$4" <<'PY'
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
path.write_text(path.read_text().replace(sys.argv[2], sys.argv[3]))
PY
    ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    terraform.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603 - resolved Bash runs a repository-owned script.
        [bash, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "STATE_PATH": str(state_path),
            "MOVE_LOG": str(log_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        },
    )


@pytest.mark.parametrize(
    "old",
    (
        OLD,
        "module.measurement_runners.azurerm_container_app_job.baseline_regression",
        "module.measurement_runners.azurerm_container_app_job.baseline_regression[0]",
    ),
)
def test_reconciles_only_present_legacy_addresses(tmp_path: Path, old: str) -> None:
    result = _run(tmp_path, f"{old}\nunrelated.resource\n")

    assert result.returncode == 0
    assert (tmp_path / "moves").read_text(encoding="utf-8") == f"{old} -> {NEW}\n"
    assert "Before digest: `sha256:" in (tmp_path / "summary").read_text(encoding="utf-8")


def test_rejects_coexisting_legacy_and_current_addresses(tmp_path: Path) -> None:
    result = _run(tmp_path, f"{OLD}\n{NEW}\n")

    assert result.returncode == 1
    assert "legacy and current measurement state addresses conflict" in result.stderr
