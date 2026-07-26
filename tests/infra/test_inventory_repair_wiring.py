from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_inventory_job_wakes_frequently_but_keeps_full_scan_interval() -> None:
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert 'default     = "*/10 * * * *"' in variables
    assert "inventory_reconciliation_interval_seconds" in variables
    assert 'name  = "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS"' in job
    assert "value = tostring(var.inventory_reconciliation_interval_seconds)" in job


def test_inventory_repair_does_not_grant_core_job_operator_permission() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert "executor_inventory_job_operator" not in root
    assert "Container Apps Jobs Operator" not in root
