from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEV_ACCESS = _ROOT / "tools" / "dev-access"


def test_dev_access_is_an_independent_terraform_root() -> None:
    versions = (_DEV_ACCESS / "infra" / "versions.tf").read_text(encoding="utf-8")
    main = (_DEV_ACCESS / "infra" / "main.tf").read_text(encoding="utf-8")
    production = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.9"' in versions
    assert 'resource "azurerm_resource_group" "dev_access"' in main
    assert 'resource "azurerm_virtual_network" "dev_access"' in main
    assert 'resource "azurerm_virtual_network_gateway" "dev_access"' in main
    assert 'resource "azurerm_private_dns_resolver" "dev_access"' in main
    assert "dev-access" not in production


def test_dev_access_uses_entra_openvpn_and_private_dns() -> None:
    main = (_DEV_ACCESS / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'name                 = "GatewaySubnet"' in main
    assert 'name    = "Microsoft.Network/dnsResolvers"' in main
    assert 'vpn_client_protocols = ["OpenVPN"]' in main
    assert 'vpn_auth_types       = ["AAD"]' in main
    assert "aad_tenant" in main
    assert "aad_audience" in main
    assert "aad_issuer" in main
    assert 'zones               = ["1", "2", "3"]' in main
    assert 'resource "azurerm_private_dns_resolver_inbound_endpoint" "dev_access"' in main
    assert 'resource "azurerm_virtual_network_dns_servers" "dev_access"' in main
    assert 'resource "azurerm_private_dns_zone_virtual_network_link" "fdai"' in main


def test_dev_access_owns_only_removable_fdai_connections() -> None:
    main = (_DEV_ACCESS / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_virtual_network_peering" "dev_access_to_fdai"' in main
    assert 'resource "azurerm_virtual_network_peering" "fdai_to_dev_access"' in main
    assert re.search(r"allow_gateway_transit\s*=\s*true", main)
    assert re.search(r"use_remote_gateways\s*=\s*true", main)
    assert re.search(r"allow_forwarded_traffic\s*=\s*true", main)
    assert "azurerm_virtual_network_gateway.dev_access" in main
    assert "azurerm_role_assignment" not in main
    assert "ignore_changes = [ip_tags]" in main
    assert "ignore_changes = [tags]" in main

    variables = (_DEV_ACCESS / "infra" / "variables.tf").read_text(encoding="utf-8")
    assert 'default     = "VpnGw1AZ"' in variables


def test_dev_access_ships_repeatable_client_checks() -> None:
    profile = (_DEV_ACCESS / "scripts" / "profile.sh").read_text(encoding="utf-8")
    doctor = (_DEV_ACCESS / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    wsl_dns = (_DEV_ACCESS / "scripts" / "wsl-dns.sh").read_text(encoding="utf-8")

    assert "az network vnet-gateway vpn-client generate" in profile
    assert "terraform output -raw dns_resolver_inbound_ip" in profile
    assert "from zipfile import ZipFile" in profile
    assert "networkingMode=mirrored" in doctor
    assert "dnsTunneling=true" in doctor
    assert "getent ahostsv4" in doctor
    assert "END { print answer }" in doctor
    assert 'ACTION="${1:-apply}"' in wsl_dns
    assert "resolvectl dnsovertls" in wsl_dns
    assert "wsl.exe" in wsl_dns
