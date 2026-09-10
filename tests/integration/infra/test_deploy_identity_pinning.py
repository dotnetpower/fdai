"""Regression tests for stable deploy identity pinning."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_platform_deployer_roles_use_the_configured_stable_principal() -> None:
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    main = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'variable "deploy_runner_principal_id"' in variables
    assert main.count("var.deploy_runner_principal_id") == 11
    assert not any(
        "data.azurerm_client_config.current.object_id" in line
        and ("deployer_principal_id" in line or "deployer =" in line)
        for line in main.splitlines()
    )
    assert 'resource "terraform_data" "deploy_runner_identity_fence"' in main


def test_protected_deploy_binds_model_and_terraform_to_the_same_principal() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")

    assert "TF_VAR_deploy_runner_principal_id: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
    assert "MODEL_RESOLVER_DEPLOYER_OBJECT_ID: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow


def test_scenario_deployer_roles_use_the_same_stable_principal_and_fence() -> None:
    scenario_root = _ROOT / "infra" / "scenario-lab"
    variables = (scenario_root / "variables.tf").read_text(encoding="utf-8")
    main = (scenario_root / "main.tf").read_text(encoding="utf-8")
    aks = (scenario_root / "aks.tf").read_text(encoding="utf-8")
    data_services = (scenario_root / "data-services.tf").read_text(encoding="utf-8")
    workflow = (_ROOT / ".github" / "workflows" / "sre-demo-lab.yml").read_text(encoding="utf-8")

    assert 'variable "deploy_runner_principal_id"' in variables
    assert 'resource "terraform_data" "deploy_runner_identity_fence"' in main
    assert aks.count("principal_id         = var.deploy_runner_principal_id") == 2
    assert "executor_principal_id = var.deploy_runner_principal_id" in data_services
    assert "data.azurerm_client_config.current.object_id" not in aks
    assert "data.azurerm_client_config.current.object_id" not in data_services
    assert "TF_VAR_deploy_runner_principal_id: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
