from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]


def _load_jsonc(path: Path) -> Any:
    content = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    return json.loads(content)


def test_inventory_job_wakes_every_minute_but_keeps_full_scan_interval() -> None:
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert 'default     = "* * * * *"' in variables
    assert "inventory_reconciliation_interval_seconds" in variables
    assert 'name  = "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS"' in job
    assert "value = tostring(var.inventory_reconciliation_interval_seconds)" in job


def test_inventory_job_carries_continuous_collection_budgets() -> None:
    root_variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    module_call = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    module_variables = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "variables.tf"
    ).read_text(encoding="utf-8")
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    names = (
        "inventory_change_min_interval_seconds",
        "inventory_progress_deadline_seconds",
        "inventory_attempt_deadline_seconds",
        "inventory_arg_requests_per_second",
    )
    for name in names:
        assert f'variable "{name}"' in root_variables
        assert f'variable "{name}"' in module_variables
        assert f"{name}" in module_call
        assert f"value = tostring(var.{name})" in job

    for key in (
        "FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS",
        "FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS",
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


def test_local_inventory_task_binds_the_deployed_change_event_ingress() -> None:
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")
    tasks = _load_jsonc(_ROOT / ".vscode" / "tasks.json")
    commands = [
        task["command"]
        for task in tasks["tasks"]
        if "fdai.delivery.inventory_sync_cli --loop" in task.get("command", "")
    ]

    assert 'name  = "FDAI_INVENTORY_RECOVERY_DELTA"' in job
    assert len(commands) == 1
    assert "FDAI_INVENTORY_RECOVERY_DELTA=1" in commands[0]
    assert "FDAI_EXECUTION_VENUE=local" in commands[0]


def test_inventory_repair_does_not_grant_core_job_operator_permission() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert "executor_inventory_job_operator" not in root
    assert "Container Apps Jobs Operator" not in root
