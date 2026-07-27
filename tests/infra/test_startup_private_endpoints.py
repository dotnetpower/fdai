from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


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
