from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_dsn_rotation_uses_versionless_rbac_and_a_versioned_runtime_reference() -> None:
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert "azurerm_key_vault_secret.state_store_dsn.id" in root
    resource = 'resource "azurerm_key_vault_secret" "state_store_dsn"'
    start = root.index(resource)
    block = root[start : root.index("\n}", start) + 2]
    assert "expiration_date" not in block

    assert "azurerm_key_vault_secret.state_store_dsn.resource_versionless_id" in root
    assert 'resource "azurerm_key_vault_secret" "operator_memory_dsn"' not in root
    assert 'resource "azurerm_key_vault_secret" "pattern_library_dsn"' not in root
