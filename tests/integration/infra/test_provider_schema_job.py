"""Global provider-schema watcher Job deployment contract."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JOB = _ROOT / "infra/provider_schema_job.tf"
_MAIN = _ROOT / "infra/main.tf"
_VARIABLES = _ROOT / "infra/variables.tf"
_CORE_DOCKERFILE = _ROOT / "services/core-control-plane/docker/Dockerfile"
_COST_DOCKERFILE = _ROOT / "extensions/cost-governance/docker/Dockerfile"


def test_provider_schema_job_is_scheduled_durable_and_publishes_through_pantheon() -> None:
    job = _JOB.read_text(encoding="utf-8")
    main = _MAIN.read_text(encoding="utf-8")
    variables = _VARIABLES.read_text(encoding="utf-8")

    assert "cron_expression          = var.provider_schema_cron_expression" in job
    assert (
        'command = ["python", "-m", "fdai.delivery.provider_schema_watcher_cli", "--force"]' in job
    )
    assert 'name    = "provider-schema"' in job
    assert 'workload_profile_name        = "Consumption"' in job
    assert "replica_timeout_in_seconds   = 1800" in job
    assert 'name        = "FDAI_PROVIDER_SCHEMA_DSN"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_NETWORK_POLICY"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_PRIMARY_REPO"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_PRIMARY_REF"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_CADENCE_SECONDS"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_FETCH_TIMEOUT_SECONDS"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_MIN_TYPES"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_MAX_TYPES"' in job
    assert 'name  = "KAFKA_BOOTSTRAP_SERVERS"' in job
    assert 'name  = "FDAI_MI_CLIENT_ID"' in job
    assert 'name  = "FDAI_PROVIDER_SCHEMA_REVIEW_COMPATIBLE"' in job
    assert 'value = "1"' in job
    assert 'value = "public"' in job
    assert "replica_retry_limit          = 0" in job
    assert job.count("module.compute.azurerm_container_app_job.provider_schema[0]") == 1
    assert job.count("module.") == 1
    assert "provider_schema_cron_expression" not in main
    assert 'variable "provider_schema_cron_expression"' in variables
    assert 'default     = "0 4 * * *"' in variables
    for dockerfile_path in (_CORE_DOCKERFILE, _COST_DOCKERFILE):
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        assert "COPY --chown=65532:65532 provider-schema-catalog/" in dockerfile
        assert "ARG GIT_VERSION=2.55.0-r1" in dockerfile
        assert '"git=${GIT_VERSION}"' in dockerfile
        assert "&& git --version" in dockerfile


def test_provider_schema_job_uses_only_the_read_only_inventory_identity() -> None:
    job = _JOB.read_text(encoding="utf-8")

    assert "container_app_environment_id = local.provider_schema_environment_id" in job
    assert job.count("local.provider_schema_inventory_identity_id") == 3
    assert 'data "azurerm_container_app_environment" "provider_schema"' not in job
    assert "data.azurerm_user_assigned_identity.provider_schema_inventory[0].client_id" in job
    assert "module.inventory_identity" not in job
    assert "module.event_bus" not in job
    assert "grants_authority" not in job
