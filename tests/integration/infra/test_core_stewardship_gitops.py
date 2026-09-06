from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_MAIN = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
_PLATFORM_OUTPUTS = (_ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")
_DEPLOY_WORKFLOW = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")
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
_INGESTION_ROOT = (_ROOT / "infra" / "services" / "document-ingestion-api" / "main.tf").read_text(
    encoding="utf-8"
)
_INGESTION_VARIABLES = (
    _ROOT / "infra" / "services" / "document-ingestion-api" / "variables.tf"
).read_text(encoding="utf-8")
_INGESTION_MODULE = (
    _ROOT
    / "infra"
    / "services"
    / "document-ingestion-api"
    / "modules"
    / "document-ingestion-api"
    / "main.tf"
).read_text(encoding="utf-8")


def test_platform_exports_review_only_stewardship_gitops_binding() -> None:
    assert 'output "stewardship_gitops_binding"' in _PLATFORM_OUTPUTS
    assert "auth_mode                 = trimspace(" in _PLATFORM_OUTPUTS
    assert "azurerm_key_vault_secret.gitops_token[0].resource_versionless_id" in _PLATFORM_OUTPUTS
    assert (
        "azurerm_key_vault_secret.github_app_private_key[0].resource_versionless_id"
        in _PLATFORM_OUTPUTS
    )
    assert (
        "azurerm_key_vault_secret.github_webhook_secret[0].resource_versionless_id"
        in _PLATFORM_OUTPUTS
    )
    assert 'resource "azurerm_role_assignment" "core_gitops_secret_reader"' in _PLATFORM_MAIN
    assert (
        'resource "azurerm_role_assignment" "core_github_app_private_key_reader"' in _PLATFORM_MAIN
    )
    assert (
        'resource "azurerm_role_assignment" "ingestion_github_auth_secret_reader"' in _PLATFORM_MAIN
    )
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
    assert 'name                = "stewardship-github-app-private-key"' in _SERVICE_MODULE
    assert (
        "key_vault_secret_id = var.stewardship_gitops.app_private_key_secret_id" in _SERVICE_MODULE
    )
    assert (
        '{ name = "FDAI_GITHUB_APP_PRIVATE_KEY", '
        'secret_name = "stewardship-github-app-private-key" }' in _SERVICE_MODULE
    )


def test_document_ingestion_receives_signed_webhook_and_refreshable_auth() -> None:
    assert "stewardship_gitops   = var.stewardship_gitops" in _INGESTION_ROOT
    assert 'variable "stewardship_gitops"' in _INGESTION_VARIABLES
    assert "FDAI_STEWARDSHIP_GITHUB_WEBHOOK_ENABLED" in _INGESTION_MODULE
    assert "FDAI_STEWARDSHIP_REPOSITORY_INTAKE_ENABLED" in _INGESTION_MODULE
    assert "FDAI_GITHUB_WEBHOOK_SECRET" in _INGESTION_MODULE
    assert "FDAI_GITHUB_APP_PRIVATE_KEY" in _INGESTION_MODULE
    assert "value = var.stewardship_gitops.webhook_secret_id" not in _INGESTION_MODULE


def test_platform_workflow_binds_stewardship_inputs_without_exposing_secrets() -> None:
    assert (
        "TF_VAR_enable_stewardship_governance: "
        "${{ vars.ENABLE_STEWARDSHIP_GOVERNANCE == 'true' }}" in _DEPLOY_WORKFLOW
    )
    assert "TF_VAR_gitops_owner: ${{ vars.GITOPS_OWNER }}" in _DEPLOY_WORKFLOW
    assert "TF_VAR_gitops_repo: ${{ vars.GITOPS_REPO }}" in _DEPLOY_WORKFLOW
    assert "TF_VAR_github_app_client_id: ${{ vars.GITHUB_APP_CLIENT_ID }}" in _DEPLOY_WORKFLOW
    assert (
        "TF_VAR_github_app_installation_id: ${{ vars.GITHUB_APP_INSTALLATION_ID }}"
        in _DEPLOY_WORKFLOW
    )
    assert "TF_VAR_gitops_token: ${{ secrets.GITOPS_TOKEN }}" in _DEPLOY_WORKFLOW
    assert (
        "TF_VAR_github_app_private_key: ${{ secrets.GITHUB_APP_PRIVATE_KEY }}" in _DEPLOY_WORKFLOW
    )
    assert "TF_VAR_github_webhook_secret: ${{ secrets.GITHUB_WEBHOOK_SECRET }}" in _DEPLOY_WORKFLOW
    assert "TF_VAR_gitops_token: ${{ vars." not in _DEPLOY_WORKFLOW
    assert "TF_VAR_github_webhook_secret: ${{ vars." not in _DEPLOY_WORKFLOW
