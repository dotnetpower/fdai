from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ohl_evidence_subnet_denies_internet_inbound() -> None:
    module = (ROOT / "infra/modules/network/main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_network_security_group" "evidence_target"' in module
    assert (
        'resource "azurerm_subnet_network_security_group_association" "evidence_target"' in module
    )
    assert "subnet_id                 = azurerm_subnet.evidence_target[0].id" in module
    assert (
        "network_security_group_id = azurerm_network_security_group.evidence_target[0].id" in module
    )
    assert 'source_address_prefix      = "Internet"' in module
    assert 'access                     = "Deny"' in module


def test_operator_access_vnets_use_direct_non_transitive_peering() -> None:
    main = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")

    assert 'variable "operator_access_vnets"' in variables
    assert 'resource "azurerm_virtual_network_peering" "spoke_to_operator"' in main
    assert 'resource "azurerm_virtual_network_peering" "operator_to_spoke"' in main
    assert "for_each                     = local.operator_access_vnets" in main
    assert main.count("allow_forwarded_traffic      = false") >= 2
    assert "depends_on = [azurerm_virtual_network_peering.spoke_to_operator]" in main


def test_operator_access_vnets_link_only_explicit_private_dns_zones() -> None:
    main = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")

    assert 'variable "operator_private_dns_zones"' in variables
    assert "operator_private_dns_links = merge({}, [" in main
    assert "for zone_key, zone in var.operator_private_dns_zones" in main
    assert 'resource "azurerm_private_dns_zone_virtual_network_link" "operator_access"' in main
    assert 'name                  = "link-operator-${each.key}"' in main
    assert "registration_enabled  = false" in main


def test_operator_inventory_identity_receives_only_reader() -> None:
    main = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")

    assert 'variable "operator_inventory_principal_ids"' in variables
    assert 'resource "azurerm_role_assignment" "operator_inventory_reader"' in main
    assert 'role_definition_name = "Reader"' in main
    assert "for_each = var.operator_inventory_principal_ids" in main
