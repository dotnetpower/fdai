from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_postgres_audits_connections_and_checkpoints() -> None:
    module = (ROOT / "infra/modules/state-store/postgres-flex/main.tf").read_text(encoding="utf-8")

    for resource_name, parameter_name in (
        ("log_connections", "log_connections"),
        ("log_checkpoints", "log_checkpoints"),
    ):
        resource = f'resource "azurerm_postgresql_flexible_server_configuration" "{resource_name}"'
        start = module.index(resource)
        block = module[start : module.index("\n}", start) + 2]
        assert f'name      = "{parameter_name}"' in block
        assert "server_id = azurerm_postgresql_flexible_server.primary.id" in block
        assert 'value     = "on"' in block
