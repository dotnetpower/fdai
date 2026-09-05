from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "compute" / "container-apps"


def test_operational_history_job_is_scheduled_shadow_only() -> None:
    job = (_MODULE / "operational_history_lifecycle_job.tf").read_text(encoding="utf-8")

    assert "inventory_identity_id" in job
    assert "executor_identity" not in job
    assert 'args    = ["--mode", "shadow"]' in job
    assert "AUTHORITY_RECEIPT" not in job
    assert "replica_completion_count = 1" in job
    assert "parallelism              = 1" in job
    assert 'name        = "FDAI_DATABASE_URL"' in job
    assert 'name  = "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL"' in job


def test_operational_history_job_has_dedicated_private_storage() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    storage = (_ROOT / "infra" / "modules" / "storage" / "case-history" / "main.tf").read_text(
        encoding="utf-8"
    )

    assert 'module "operational_history_storage"' in root
    assert "count  = var.enable_operational_history ? 1 : 0" in root
    assert 'container_name                = "operational-history"' in root
    assert "runtime_principal_id          = module.inventory_identity.principal_id" in root
    assert 'resource "azurerm_private_endpoint" "operational_history_blob"' in root
    assert (
        "private_dns_zone_ids = [module.case_history_blob_private_endpoint[0].private_dns_zone_id]"
    ) in root
    assert 'private_dns_zone_name = "privatelink.blob.core.windows.net"' in root
    assert "shared_access_key_enabled         = false" in storage
    assert "public_network_access_enabled     = var.public_network_access_enabled" in storage
    assert 'role_definition_name = "Storage Blob Data Contributor"' in storage


def test_operational_history_wiring_exposes_bounded_controls_and_outputs() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    root_variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    root_outputs = (_ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")
    module_outputs = (_MODULE / "outputs.tf").read_text(encoding="utf-8")

    assert "operational_history_lifecycle_cron_expression" in root
    assert "operational_history_lifecycle_max_partitions" in root
    assert "operational_history_lifecycle_max_partitions <= 256" in root_variables
    assert 'default     = "0 * * * *"' in _variable_block(
        root_variables, "operational_history_lifecycle_cron_expression"
    )
    assert 'output "operational_history_lifecycle_job_id"' in module_outputs
    assert 'output "operational_history_lifecycle_job_id"' in root_outputs
    assert 'output "operational_history_container_url"' in root_outputs


def _variable_block(source: str, name: str) -> str:
    start = source.index(f'variable "{name}"')
    end = source.index("\n}\n", start) + 3
    return source[start:end]
