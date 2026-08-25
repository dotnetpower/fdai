"""Static contracts for the private Azure OpenAI Terraform module."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_MAIN = REPO_ROOT / "infra" / "modules" / "llm" / "azure-openai" / "main.tf"
MODULE_VARIABLES = REPO_ROOT / "infra" / "modules" / "llm" / "azure-openai" / "variables.tf"
ROOT_MAIN = REPO_ROOT / "infra" / "main.tf"
ROOT_VARIABLES = REPO_ROOT / "infra" / "variables.tf"


def test_account_enforces_private_access_and_preserves_policy_acls() -> None:
    module = MODULE_MAIN.read_text(encoding="utf-8")

    assert "public_network_access_enabled = false" in module
    assert "local_auth_enabled            = false" in module
    assert 'identity {\n    type = "SystemAssigned"' in module
    assert "ignore_changes = [network_acls]" in module


def test_operator_api_role_assignment_rename_preserves_state() -> None:
    root = ROOT_MAIN.read_text(encoding="utf-8")

    assert (
        "from = module.llm_azure_openai[0].azurerm_role_assignment."
        'additional_openai_user["read_api"]'
    ) in root
    assert (
        "to   = module.llm_azure_openai[0].azurerm_role_assignment."
        'additional_openai_user["operator_api"]'
    ) in root


def test_deployment_pins_resolver_selected_model_version() -> None:
    module = MODULE_MAIN.read_text(encoding="utf-8")
    variables = MODULE_VARIABLES.read_text(encoding="utf-8")
    root_variables = ROOT_VARIABLES.read_text(encoding="utf-8")

    assert "version = each.value.version" in module
    assert "ignore_changes = [model[0].version]" not in module
    assert "version        = string" in variables
    assert "resolved capabilities MUST pin a non-empty model version" in variables
    assert "version        = string" in root_variables
    assert "resolved capabilities MUST pin a non-empty model version" in root_variables
