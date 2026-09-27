from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_private_networking_closes_event_hubs_and_wires_shared_dns() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    module = (_ROOT / "infra" / "modules" / "event-bus" / "event-hubs-kafka" / "main.tf").read_text(
        encoding="utf-8"
    )

    assert "public_network_access_enabled = var.public_network_access_enabled" in module
    assert root.count("public_network_access_enabled = !var.enable_private_networking") >= 2
    assert 'module "event_bus_private_endpoint"' in root
    assert 'resource "azurerm_private_endpoint" "event_bus_auxiliary_shared_dns"' in root
    assert 'private_dns_zone_name = "privatelink.servicebus.windows.net"' in root
    assert "module.event_bus_private_endpoint[0].private_dns_zone_id" in root


def test_aks_policy_forced_data_plane_recovery_is_focused() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")

    assert 'variable "enable_aks_key_vault_private_access"' in variables
    assert 'variable "enable_aks_document_storage_private_access"' in variables
    assert re.search(
        r"key_vault_private_access\s*=\s*"
        r"var\.enable_private_networking \|\| var\.enable_aks_key_vault_private_access",
        root,
    )
    assert "public_network_access_enabled = !local.key_vault_private_access" in root
    assert (
        'network_acls_default_action   = local.key_vault_private_access ? "Deny" : "Allow"' in root
    )
    assert "count                 = local.key_vault_private_access ? 1 : 0" in root
    assert re.search(
        r"document_storage_private_access\s*=\s*"
        r"var\.enable_private_networking \|\| "
        r"var\.enable_aks_document_storage_private_access",
        root,
    )
    assert "public_network_access_enabled   = !local.document_storage_private_access" in root
    assert (
        root.count("var.enable_document_ingestion && local.document_storage_private_access ? 1 : 0")
        == 2
    )
    assert (
        root.count(
            'extra_vnet_links      = var.runner_vnet_id != "" ? { ops = var.runner_vnet_id } : {}'
        )
        >= 3
    )
    blob_start = root.index('module "document_blob_private_endpoint"')
    blob_end = root.index('module "case_history_blob_private_endpoint"', blob_start)
    assert "extra_vnet_links" not in root[blob_start:blob_end]
    assert 'resource "azurerm_private_dns_a_record" "document_blob_ops"' in root
    assert (
        "var.enable_document_ingestion && local.document_storage_private_access "
        '&& var.runner_vnet_id != "" && var.ops_resource_group_name != ""'
    ) in root
    assert "local.key_vault_private_access || local.document_storage_private_access" in root
    assert 'check "aks_focused_private_access_runner_path"' in root
    assert "public_network_access_enabled = !var.enable_private_networking" in root


def test_public_mode_postgres_gets_additive_private_endpoint() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'module "postgres_public_mode_private_endpoint"' in root
    assert "var.enable_private_networking && !var.enable_private_postgres" in root
    assert 'subresource_name      = "postgresqlServer"' in root
    assert 'private_dns_zone_name = "privatelink.postgres.database.azure.com"' in root
    assert "public_network_access_enabled = !var.enable_private_networking" in root
    assert "allow_azure_services_firewall = !var.enable_private_networking" in root


def test_premium_registry_is_locked_behind_a_private_endpoint() -> None:
    """A private-everything tenant MUST NOT keep the image registry public."""
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'acr_private_link = var.enable_private_networking && var.acr_sku == "Premium"' in root
    assert 'module "acr_private_endpoint"' in root
    assert "count                 = local.acr_private_link ? 1 : 0" in root
    assert 'subresource_name      = "registry"' in root
    assert 'private_dns_zone_name = "privatelink.azurecr.io"' in root
    assert "public_network_access_enabled = !local.acr_private_link" in root

    module = (_ROOT / "infra/modules/container-registry/main.tf").read_text(encoding="utf-8")
    assert 'data_endpoint_enabled         = var.sku == "Premium"' in module
    assert 'retention_policy_in_days      = var.sku == "Premium" ? 30 : null' in module


def test_non_premium_registry_stays_reachable() -> None:
    """Basic and Standard registries have no private-link path; closing them
    publicly would break every image pull, so the module default stays open.
    """
    module = (_ROOT / "infra" / "modules" / "container-registry" / "main.tf").read_text(
        encoding="utf-8"
    )
    variables = (_ROOT / "infra" / "modules" / "container-registry" / "variables.tf").read_text(
        encoding="utf-8"
    )

    assert "public_network_access_enabled = var.public_network_access_enabled" in module
    assert 'variable "public_network_access_enabled"' in variables
    assert "default     = true" in variables
