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
