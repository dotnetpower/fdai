from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_MAIN = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
_PLATFORM_OUTPUTS = (_ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")
_SERVICE_ROOT = (_ROOT / "infra" / "services" / "core-control-plane" / "main.tf").read_text(
    encoding="utf-8"
)
_SERVICE_VARIABLES = (
    _ROOT / "infra" / "services" / "core-control-plane" / "variables.tf"
).read_text(encoding="utf-8")
_SERVICE_MODULE = (
    _ROOT
    / "infra"
    / "services"
    / "core-control-plane"
    / "modules"
    / "core-control-plane"
    / "main.tf"
).read_text(encoding="utf-8")


def test_platform_exports_review_only_stewardship_gitops_binding() -> None:
    assert 'output "stewardship_gitops_binding"' in _PLATFORM_OUTPUTS
    assert (
        "token_secret_id = azurerm_key_vault_secret.gitops_token[0].resource_versionless_id"
        in _PLATFORM_OUTPUTS
    )
    assert 'resource "azurerm_role_assignment" "core_gitops_secret_reader"' in _PLATFORM_MAIN
    assert 'role_definition_name = "Key Vault Secrets User"' in _PLATFORM_MAIN


def test_core_service_receives_gitops_only_as_key_vault_reference() -> None:
    assert "stewardship_gitops" in _SERVICE_ROOT
    assert "= var.stewardship_gitops" in _SERVICE_ROOT
    assert 'variable "stewardship_gitops"' in _SERVICE_VARIABLES
    assert 'name                = "stewardship-gitops-token"' in _SERVICE_MODULE
    assert "key_vault_secret_id = var.stewardship_gitops.token_secret_id" in _SERVICE_MODULE
    assert (
        '{ name = "FDAI_GITOPS_TOKEN", secret_name = "stewardship-gitops-token" }'
        in _SERVICE_MODULE
    )
    assert "value = var.stewardship_gitops.token_secret_id" not in _SERVICE_MODULE
