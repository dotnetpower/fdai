"""Deployment contract for the opt-in automation blueprint tick job."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_MODULE = ROOT / "infra/modules/compute/container-apps"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_automation_blueprint_tick_is_opt_in_and_runs_the_core_cli() -> None:
    job = _normalized(_MODULE / "automation_blueprint_job.tf")
    module_variables = _normalized(_MODULE / "variables.tf")
    root_variables = _normalized(ROOT / "infra/variables.tf")
    root = _normalized(ROOT / "infra/main.tf")

    assert 'count = var.automation_blueprint_cron_expression == "" ? 0 : 1' in job
    assert 'command = ["python", "-m", "fdai.delivery.automation_blueprint_tick_cli"]' in job
    assert "cron_expression = var.automation_blueprint_cron_expression" in job
    for variables in (module_variables, root_variables):
        assert 'variable "automation_blueprint_cron_expression" { description = "' in variables
    assert "automation_blueprint_cron_expression = var.automation_blueprint_cron_expression" in root
    assert (
        'var.scheduler_tick_cron_expression != "" || var.automation_blueprint_cron_expression != ""'
        in root
    )


def test_automation_blueprint_tick_reads_only_the_state_store_secret_under_scheduler_identity() -> (
    None
):
    job = _normalized(_MODULE / "automation_blueprint_job.tf")

    assert "identity_ids = [var.scheduler_identity_id]" in job
    assert "key_vault_secret_id = var.state_store_dsn_secret_id" in job
    assert 'name = "FDAI_AUTOMATION_BLUEPRINT_DSN" secret_name = "automation-blueprint-dsn"' in job
    assert "precondition" in job and 'var.scheduler_identity_client_id != ""' in job
    assert "executor_identity" not in job
    assert "replica_completion_count = 1 parallelism = 1" in job
