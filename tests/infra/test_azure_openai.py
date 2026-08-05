"""Static contracts for the private Azure OpenAI Terraform module."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_MAIN = REPO_ROOT / "infra" / "modules" / "llm" / "azure-openai" / "main.tf"
ROOT_MAIN = REPO_ROOT / "infra" / "main.tf"


def test_account_enforces_private_access_and_preserves_policy_acls() -> None:
    module = MODULE_MAIN.read_text(encoding="utf-8")

    assert "public_network_access_enabled = false" in module
    assert "local_auth_enabled            = false" in module
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
