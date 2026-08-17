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
