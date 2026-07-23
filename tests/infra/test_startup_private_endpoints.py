from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def test_private_networking_closes_event_hubs_and_wires_shared_dns() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    module = (
        _ROOT / "infra" / "modules" / "event-bus" / "event-hubs-kafka" / "main.tf"
    ).read_text(encoding="utf-8")

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