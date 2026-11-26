from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_dev_gateway_storage_is_keyless_recoverable_and_observable() -> None:
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert "shared_access_key_enabled       = false" in root
    assert "local_user_enabled              = false" in root
    assert root.count("days = 7") >= 2
    assert 'resource "azurerm_monitor_diagnostic_setting" "dev_gateway_blob"' in root
    assert 'category = "StorageRead"' in root
    assert 'category = "StorageWrite"' in root
    assert 'category = "StorageDelete"' in root
