from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_document_storage_disables_local_users_and_emits_blob_diagnostics() -> None:
    module = (ROOT / "infra/modules/storage/adls-gen2/main.tf").read_text(encoding="utf-8")
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert "shared_access_key_enabled         = false" in module
    assert "local_user_enabled                = false" in module
    assert 'resource "azurerm_monitor_diagnostic_setting" "document_blob"' in module
    assert 'category = "StorageRead"' in module
    assert 'category = "StorageWrite"' in module
    assert 'category = "StorageDelete"' in module
    assert "log_analytics_workspace_id      = module.log_analytics.workspace_id" in root
