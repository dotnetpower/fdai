from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_foundry_web_search_uses_identity_and_private_mode() -> None:
    module = (ROOT / "infra/modules/llm/foundry-web-search/main.tf").read_text(encoding="utf-8")
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert "public_network_access_enabled = !var.private_networking_enabled" in module
    assert "local_auth_enabled            = false" in module
    assert 'identity {\n    type = "SystemAssigned"' in module
    assert 'module "foundry_web_search_private_endpoint"' in root
    assert 'private_dns_zone_name = "privatelink.services.ai.azure.com"' in root
