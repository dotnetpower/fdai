"""Regression tests for stable deploy identity pinning."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_platform_deployer_roles_use_the_configured_stable_principal() -> None:
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    main = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'variable "deploy_runner_principal_id"' in variables
    assert main.count("var.deploy_runner_principal_id") == 9
    assert not any(
        "data.azurerm_client_config.current.object_id" in line
        and ("deployer_principal_id" in line or "deployer =" in line)
        for line in main.splitlines()
    )


def test_protected_deploy_binds_model_and_terraform_to_the_same_principal() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")

    assert "TF_VAR_deploy_runner_principal_id: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
    assert "MODEL_RESOLVER_DEPLOYER_OBJECT_ID: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
