from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_case_history_storage_is_private_versioned_and_keyless() -> None:
    module = (ROOT / "infra/modules/storage/case-history/main.tf").read_text(encoding="utf-8")
    assert "shared_access_key_enabled         = false" in module
    assert "default_to_oauth_authentication   = true" in module
    assert "versioning_enabled  = true" in module
    assert 'container_access_type = "private"' in module
    assert 'role_definition_name = "Storage Blob Data Contributor"' in module
    assert "delete_after_days_since_creation = var.version_retention_days" in module
    assert 'bypass         = ["None"]' in module
    assert 'dynamic "private_link_access"' in module
    assert "for_each = var.private_link_access" in module


def test_root_wires_case_history_private_endpoint_and_core_environment() -> None:
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    compute = (ROOT / "infra/modules/compute/container-apps/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    assert 'module "case_history_storage"' in root
    assert 'module "case_history_identity"' in root
    assert "runtime_principal_id          = module.case_history_identity[0].principal_id" in root
    assert "private_link_access = var.enable_private_networking ? {" in root
    assert "Microsoft.Security/datascanners/StorageDataScanner" in root
    assert "module.case_history_identity[0].resource_id" in root
    assert 'module "case_history_blob_private_endpoint"' in root
    assert 'private_dns_zone_name = "privatelink.blob.core.windows.net"' in root
    assert "FDAI_CASE_HISTORY_CONTAINER_URL" in compute
    assert "FDAI_CASE_HISTORY_MI_CLIENT_ID" in compute
    assert "FDAI_CASE_HISTORY_RETENTION_DAYS" in compute
    assert "FDAI_CASE_HISTORY_DELETION_DAYS" in compute
    assert 'variable "enable_case_history"' in variables
    assert "default     = true" in variables


def test_forecast_tick_is_mechanical_and_opt_in() -> None:
    job = (ROOT / "infra/modules/compute/container-apps/forecast_tick_job.tf").read_text(
        encoding="utf-8"
    )
    module_variables = (ROOT / "infra/modules/compute/container-apps/variables.tf").read_text(
        encoding="utf-8"
    )
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    assert 'count = var.forecast_tick_cron_expression == "" ? 0 : 1' in job
    assert '"fdai.delivery.forecast_tick_cli"' in job
    assert "forecast_tick_cron_expression = var.forecast_tick_cron_expression" in root
    assert 'variable "forecast_targets_json"' in module_variables
