"""Rule collector Job deployment contract."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JOB = _ROOT / "infra/modules/compute/container-apps/rule_watcher_job.tf"
_MAIN = _ROOT / "infra/main.tf"
_VARIABLES = _ROOT / "infra/variables.tf"


def test_rule_collector_job_is_scheduled_and_records_verified_evidence() -> None:
    job = _JOB.read_text(encoding="utf-8")
    main = _MAIN.read_text(encoding="utf-8")
    variables = _VARIABLES.read_text(encoding="utf-8")

    assert "cron_expression          = var.rule_watcher_cron_expression" in job
    assert 'command = ["python", "-m", "fdai.delivery.rule_collector_job_cli"]' in job
    assert 'name        = "FDAI_STATE_STORE_DSN"' in job
    assert "rule_watcher_cron_expression = var.rule_watcher_cron_expression" in main
    assert 'variable "rule_watcher_cron_expression"' in variables
    assert 'default     = "0 3 * * *"' in variables


def test_rule_collector_job_never_receives_the_executor_identity() -> None:
    job = _JOB.read_text(encoding="utf-8")

    assert job.count("var.inventory_identity_id") == 3
    assert "var.executor_identity_id" not in job
