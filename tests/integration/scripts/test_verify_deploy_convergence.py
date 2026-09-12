from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/verify_deploy_convergence.sh"
_IMAGE = f"example.azurecr.io/fdai@sha256:{'a' * 64}"


def _run(
    tmp_path: Path,
    request_id: str,
    *,
    plan_exit: int = 0,
    operational_history_only: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    calls = tmp_path / "calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "terraform": """#!/usr/bin/env bash
set -euo pipefail
printf 'terraform %s;target=%s\n' "$*" "${TF_CLI_ARGS_plan:-}" >> "$CALLS"
if [[ "$1" == "plan" ]]; then exit "$PLAN_EXIT"; fi
if [[ "$*" == "output -raw resource_group_name" ]]; then printf 'rg-fdai-dev-krc'; exit 0; fi
if [[ "$*" == "output -raw cost_governance_collector_job_name" ]]; then
    printf 'cost-collector'
    exit 0
fi
if [[ "$*" == "output -raw cost_governance_analyzer_job_name" ]]; then
    printf 'cost-analyzer'
    exit 0
fi
if [[ "$*" == "output -raw provider_schema_job_id" ]]; then
    printf '/subscriptions/example/resourceGroups/example/providers/'
    printf 'Microsoft.App/jobs/provider'
    exit 0
fi
exit 90
""",
        "az": """#!/usr/bin/env bash
set -euo pipefail
printf 'az %s\n' "$*" >> "$CALLS"
printf '{"properties":{"template":{"containers":[]}}}'
""",
        "uv": """#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\n' "$*" >> "$CALLS"
""",
    }.items():
        path = bin_dir / name
        path.write_text(body, encoding="ascii")
        path.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - resolved Bash runs one repository script
        [bash, str(_SCRIPT), request_id],
        check=False,
        capture_output=True,
        text=True,
        cwd=_ROOT / "infra",
        env={
            **os.environ,
            "CALLS": str(calls),
            "OPERATIONAL_HISTORY_ONLY": str(operational_history_only).lower(),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PLAN_EXIT": str(plan_exit),
            "RUNNER_TEMP": str(tmp_path),
            "TF_VAR_cost_governance_image": _IMAGE,
            "TF_VAR_core_image": _IMAGE,
            "TF_VAR_env": "dev",
            "TF_VAR_region_short": "krc",
        },
    )
    return result, calls, tmp_path


def test_observability_apply_replans_only_updater_and_verifies_analyzer(
    tmp_path: Path,
) -> None:
    result, calls, _ = _run(tmp_path, "apply-observability-" + "a" * 48)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="ascii")
    assert "target=-target=terraform_data.observability_analyzer_image_update" in log
    assert "--name ca-fdai-dev-krc-core-analyzer" in log
    assert "--container analyzer-tick" in log


def test_general_apply_keeps_full_plan_and_inventory_verification(tmp_path: Path) -> None:
    result, calls, _ = _run(tmp_path, "apply-" + "a" * 48)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="ascii")
    assert "target=" in log
    assert "--name ca-fdai-dev-krc-core-inventory" in log
    assert "--container inventory" in log


def test_cost_apply_replans_and_verifies_both_cost_jobs(tmp_path: Path) -> None:
    result, calls, _ = _run(tmp_path, "apply-cost-" + "a" * 48)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="ascii")
    assert (
        "target=-target=azurerm_role_assignment.inventory_cost_reader "
        "-target=azurerm_container_app_job.cost_governance_collector[0] "
        "-target=azurerm_container_app_job.cost_governance_analyzer[0]"
    ) in log
    assert "--name cost-collector" in log
    assert "--container cost-governance-collector" in log
    assert "--name cost-analyzer" in log
    assert "--container cost-governance-analyzer" in log
    assert "--name ca-fdai-dev-krc-core-inventory" not in log


def test_runtime_call_apply_replans_only_transition_before_separate_readback(
    tmp_path: Path,
) -> None:
    result, calls, _ = _run(tmp_path, "apply-runtime-" + "a" * 48)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="ascii")
    assert (
        "target=-target=terraform_data.runtime_call_evidence_transition "
        "-target=terraform_data.inventory_runtime_image_update "
        "-target=terraform_data.runtime_workspace_binding_transition"
    ) in log
    assert "\naz " not in "\n" + log
    assert "\nuv " not in "\n" + log


def test_model_binding_apply_replans_only_deployments_before_separate_readback(
    tmp_path: Path,
) -> None:
    result, calls, _ = _run(tmp_path, "apply-model-" + "a" * 64)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="ascii")
    assert (
        "target=-target=module.llm_azure_openai[0].azurerm_cognitive_deployment.capability"
    ) in log
    assert "\naz " not in "\n" + log
    assert "\nuv " not in "\n" + log


def test_provider_schema_apply_replans_and_reads_only_provider_job(tmp_path: Path) -> None:
    result, calls, _ = _run(tmp_path, "apply-provider-" + "a" * 48)

    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="ascii")
    assert "target=-target=module.compute.azurerm_container_app_job.provider_schema[0]" in log
    assert "terraform output -raw provider_schema_job_id" in log
    assert "az resource show --ids " in log
    assert "--container provider-schema" in log


def test_nonconverged_plan_stops_before_live_readback(tmp_path: Path) -> None:
    result, calls, _ = _run(
        tmp_path,
        "apply-observability-" + "a" * 48,
        plan_exit=2,
    )

    assert result.returncode == 1
    assert "not converged" in result.stderr
    assert "\naz " not in "\n" + calls.read_text(encoding="ascii")
