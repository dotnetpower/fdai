from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_deployed_operator_binds_persistent_key_vault_pseudonym_key() -> None:
    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
    module = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
        encoding="utf-8"
    )
    variables = (_ROOT / "infra/modules/operator-api/container-app/variables.tf").read_text(
        encoding="utf-8"
    )

    assert 'resource "random_id" "cost_pseudonym_key"' in root
    assert "byte_length = 32" in root
    assert 'resource "azurerm_key_vault_secret" "cost_pseudonym_key"' in root
    assert "sensitive(random_id.cost_pseudonym_key[0].hex)" in root
    assert 'resource "azurerm_role_assignment" "operator_cost_pseudonym_secret_reader"' in root
    assert (
        "scope                = "
        "azurerm_key_vault_secret.cost_pseudonym_key[0].resource_versionless_id" in root
    )
    assert "cost_pseudonym_key_secret_id" in variables
    assert 'name                = "cost-pseudonym-key"' in module
    assert 'name        = "FDAI_COST_PSEUDONYM_KEY"' in module
    assert 'secret_name = "cost-pseudonym-key"' in module


def test_aks_operator_uses_the_same_key_vault_secret_name() -> None:
    outputs = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
    host = (_ROOT / "packages/deployment-cli/src/fdai_deployment_cli/standalone_host.py").read_text(
        encoding="utf-8"
    )

    assert 'output "cost_pseudonym_key_secret_name"' in outputs
    assert 'output "cost_pseudonym_key_secret_id"' in outputs
    assert '"cost_pseudonym_key_secret_name": _terraform_output(' in host
    assert '"FDAI_COST_PSEUDONYM_KEY": str(' in host
    assert 'substrate_outputs["cost_pseudonym_key_secret_name"]' in host


def test_independent_operator_service_requires_the_platform_key() -> None:
    service_root = (_ROOT / "infra/services/operator-service/main.tf").read_text(encoding="utf-8")
    service_variables = (_ROOT / "infra/services/operator-service/variables.tf").read_text(
        encoding="utf-8"
    )
    module = (_ROOT / "infra/services/operator-service/modules/operator-service/main.tf").read_text(
        encoding="utf-8"
    )

    assert "cost_pseudonym_key_secret_id" in service_root
    assert "var.cost_pseudonym_key_secret_id" in service_root
    assert 'variable "cost_pseudonym_key_secret_id"' in service_variables
    assert 'name                = "cost-pseudonym-key"' in module
    assert '{ name = "FDAI_COST_PSEUDONYM_KEY", secret_name = "cost-pseudonym-key" }' in module
