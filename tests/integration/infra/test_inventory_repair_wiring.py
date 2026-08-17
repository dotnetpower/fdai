from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_inventory_job_wakes_frequently_but_keeps_full_scan_interval() -> None:
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert 'default     = "*/10 * * * *"' in variables
    assert "inventory_reconciliation_interval_seconds" in variables
    assert 'name  = "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS"' in job
    assert "value = tostring(var.inventory_reconciliation_interval_seconds)" in job


def test_inventory_recovery_delta_is_private_network_only() -> None:
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert 'name  = "FDAI_INVENTORY_RECOVERY_DELTA"' in job
    assert 'value = var.infrastructure_subnet_id == null ? "0" : "1"' in job


def test_local_inventory_task_binds_the_deployed_change_event_ingress() -> None:
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")
    tasks = (_ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")
    local_task = next(
        line for line in tasks.splitlines() if "fdai.delivery.inventory_sync_cli --loop" in line
    )

    assert 'name  = "FDAI_INVENTORY_RECOVERY_DELTA"' in job
    assert "FDAI_INVENTORY_RECOVERY_DELTA=1" in local_task
    assert "FDAI_EXECUTION_VENUE=local" in local_task


def test_inventory_repair_does_not_grant_core_job_operator_permission() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert "executor_inventory_job_operator" not in root
    assert "Container Apps Jobs Operator" not in root
