from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_inventory_job_wakes_every_minute_but_keeps_full_scan_interval() -> None:
    """A minute cron bounds change-detection latency; the interval still bounds scans."""

    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert 'default     = "* * * * *"' in variables
    assert "inventory_reconciliation_interval_seconds" in variables
    assert 'name  = "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS"' in job
    assert "value = tostring(var.inventory_reconciliation_interval_seconds)" in job


def test_inventory_job_carries_the_continuous_scan_budgets() -> None:
    """Local and deployed runs MUST share one change, deadline, and rate contract."""

    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    for name in (
        "inventory_change_min_interval_seconds",
        "inventory_attempt_deadline_seconds",
        "inventory_arg_requests_per_second",
    ):
        assert f'variable "{name}"' in variables
        assert f"value = tostring(var.{name})" in job

    for key in (
        "FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS",
        "FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS",
        "FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND",
    ):
        assert f'name  = "{key}"' in job


def test_inventory_recovery_delta_is_private_network_only() -> None:
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert 'name  = "FDAI_INVENTORY_RECOVERY_DELTA"' in job
    assert 'value = var.infrastructure_subnet_id == null ? "0" : "1"' in job


def test_inventory_repair_does_not_grant_core_job_operator_permission() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert "executor_inventory_job_operator" not in root
    assert "Container Apps Jobs Operator" not in root
