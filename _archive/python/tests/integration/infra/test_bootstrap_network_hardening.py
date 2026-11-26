from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_runner_subnet_has_nsg_and_vm_uses_no_extension_resource() -> None:
    bootstrap = (ROOT / "infra/bootstrap/main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_network_security_group" "runner"' in bootstrap
    assert 'resource "azurerm_subnet_network_security_group_association" "runner"' in bootstrap
    assert "subnet_id                 = azurerm_subnet.runner.id" in bootstrap
    assert "network_security_group_id = azurerm_network_security_group.runner.id" in bootstrap
    assert 'source_address_prefix      = "Internet"' in bootstrap
    assert 'access                     = "Deny"' in bootstrap
    assert 'resource "azurerm_virtual_machine_extension"' not in bootstrap
