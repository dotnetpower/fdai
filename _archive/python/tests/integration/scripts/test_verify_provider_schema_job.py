"""Executable checks for protected provider-schema Job evidence collection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/verify-provider-schema-job.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *,
    execution_status: str = "Succeeded",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    state = tmp_path / "started"
    output = tmp_path / "evidence.json"
    _write_executable(
        bin_dir / "terraform",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'terraform %s\n' "$*" >> "$CALLS"
if [[ "$*" == "output -raw provider_schema_job_id" ]]; then
  printf '/subscriptions/example/resourceGroups/example/providers/'
  printf 'Microsoft.App/jobs/provider-schema'
elif [[ "$*" == "output -raw key_vault_uri" ]]; then
  printf 'https://example.vault.azure.net/'
else
  exit 90
fi
""",
    )
    _write_executable(
        bin_dir / "az",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'az %s\n' "$*" >> "$CALLS"
if [[ "$*" == *"job start"* ]]; then
  touch "$STATE"
  printf '{{"name":"provider-schema-abc123"}}'
elif [[ "$*" == *"execution show"* && "$*" == *"properties.status"* ]]; then
  printf '{execution_status}'
elif [[ "$*" == *"execution show"* && "$*" == *"containers"* ]]; then
  printf '%s' "$TF_VAR_core_image"
elif [[ "$*" == *"keyvault secret show"* ]]; then
  printf 'postgresql://masked'
else
  exit 91
fi
""",
    )
    _write_executable(
        bin_dir / "uv",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\n' "$*" >> "$CALLS"
[[ "$FDAI_PROVIDER_SCHEMA_DSN" == 'postgresql://masked' ]]
for ((index=1; index<=$#; index++)); do
  if [[ "${!index}" == "--output" ]]; then
    next=$((index + 1))
    printf '{"verified":true}\n' > "${!next}"
  fi
done
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "STATE": str(state),
        "TF_VAR_core_image": "example.azurecr.io/fdai@sha256:" + "1" * 64,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    result = subprocess.run(  # noqa: S603 - fixed repository script and test PATH
        [
            "/usr/bin/bash",
            str(_SCRIPT),
            "a" * 40,
            "b" * 40,
            "plan-123-1",
            str(output),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, calls


def test_runs_exact_job_and_verifies_durable_evidence(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="utf-8")
    assert "az containerapp job start" in log
    assert "az containerapp job execution show" in log
    assert "az keyvault secret show" in log
    assert "fdai.delivery.provider_schema_deployment_evidence" in log
    assert "postgresql://masked" not in log


def test_failed_job_stops_before_durable_readback(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, execution_status="Failed")

    assert result.returncode == 1
    assert "Job execution failed" in result.stderr
    assert "uv " not in calls.read_text(encoding="utf-8")
