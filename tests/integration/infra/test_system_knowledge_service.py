"""Focused ownership and authority checks for the System Knowledge Service root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "infra/services/system-knowledge-service"
MODULE = (SERVICE_ROOT / "modules/system-knowledge-service/main.tf").read_text(encoding="utf-8")
VARIABLES = (SERVICE_ROOT / "variables.tf").read_text(encoding="utf-8")


def test_root_owns_identity_blob_optional_bot_and_single_replica_runtime() -> None:
    for resource in (
        'resource "azurerm_user_assigned_identity" "service"',
        'resource "azurerm_storage_container" "claims"',
        'resource "azurerm_bot_service_azure_bot" "service"',
        'resource "azurerm_bot_channel_ms_teams" "service"',
    ):
        assert resource in MODULE
    for role in (
        "AcrPull",
        "Storage Blob Data Contributor",
        "Key Vault Secrets User",
    ):
        assert f'role_definition_name = "{role}"' in MODULE
    assert "var.scaling.min_replicas == 1 && var.scaling.max_replicas == 1" in VARIABLES
    assert 'microsoft_app_type            = "UserAssignedMSI"' in MODULE
    assert 'sku                           = "F0"' in MODULE
    assert "local_authentication_enabled  = false" in MODULE
    assert 'var.teams.transport == "bot_framework"' in MODULE
    assert "count                         = local.bot_framework_enabled ? 1 : 0" in MODULE


def test_runtime_environment_has_no_operational_or_executor_authority() -> None:
    for required in (
        "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL",
        "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT",
    ):
        assert required in MODULE
    for forbidden in (
        "FDAI_DATABASE_URL",
        "FDAI_EXECUTOR",
        "FDAI_KAFKA",
        "FDAI_LLM",
    ):
        assert forbidden not in MODULE
    assert "execution_authority = false" in MODULE


def test_root_has_independent_backend_and_provider_lock() -> None:
    assert 'backend "azurerm" {}' in (SERVICE_ROOT / "versions.tf").read_text(encoding="utf-8")
    assert (SERVICE_ROOT / ".terraform.lock.hcl").is_file()
