"""Global provider-schema watcher Job deployment contract."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JOB = _ROOT / "infra/modules/compute/container-apps/provider_schema_job.tf"
_MAIN = _ROOT / "infra/main.tf"
_VARIABLES = _ROOT / "infra/variables.tf"


def test_provider_schema_job_is_scheduled_durable_and_publishes_through_pantheon() -> None:
    job = _JOB.read_text(encoding="utf-8")
    main = _MAIN.read_text(encoding="utf-8")
    variables = _VARIABLES.read_text(encoding="utf-8")

    assert "cron_expression          = var.provider_schema_cron_expression" in job
    assert 'command = ["python", "-m", "fdai.delivery.provider_schema_watcher_cli"]' in job
    assert 'name        = "FDAI_PROVIDER_SCHEMA_DSN"' in job
    assert 'name  = "KAFKA_BOOTSTRAP_SERVERS"' in job
    assert 'name  = "FDAI_MI_CLIENT_ID"' in job
    assert 'value = "public"' in job
    assert "replica_retry_limit          = 0" in job
    assert "provider_schema_cron_expression = var.provider_schema_cron_expression" in main
    assert 'variable "provider_schema_cron_expression"' in variables
    assert 'default     = "0 4 * * *"' in variables


def test_provider_schema_job_uses_only_the_read_only_inventory_identity() -> None:
    job = _JOB.read_text(encoding="utf-8")

    assert job.count("var.inventory_identity_id") == 3
    assert "var.executor_identity_id" not in job
    assert "grants_authority" not in job
