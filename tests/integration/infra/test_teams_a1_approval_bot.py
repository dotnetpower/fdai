"""Focused ownership and authority checks for the Teams A1 approval bot module."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_DIR = ROOT / "infra/modules/teams-a1-approval-bot"
MAIN = (MODULE_DIR / "main.tf").read_text(encoding="utf-8")
OUTPUTS = (MODULE_DIR / "outputs.tf").read_text(encoding="utf-8")
VARIABLES = (MODULE_DIR / "variables.tf").read_text(encoding="utf-8")


def test_module_provisions_bot_channel_and_dedicated_identity() -> None:
    for resource in (
        'resource "azurerm_user_assigned_identity" "approval_bot"',
        'resource "azurerm_bot_service_azure_bot" "approval"',
        'resource "azurerm_bot_channel_ms_teams" "approval"',
    ):
        assert resource in MAIN
    assert 'microsoft_app_type            = "UserAssignedMSI"' in MAIN
    assert 'sku                           = "F0"' in MAIN
    assert "local_authentication_enabled  = false" in MAIN


def test_module_grants_no_executor_or_managed_resource_role() -> None:
    # The approval bot identity only authenticates Teams; it never carries an
    # executor or managed-resource role.
    assert "azurerm_role_assignment" not in MAIN
    assert "role_definition_name" not in MAIN


def test_module_outputs_the_teams_approval_destination_contract() -> None:
    assert 'output "teams_approval_destination"' in OUTPUTS
    for field in (
        "team_id",
        "channel_id",
        "activity_url",
        "identity_resource_id",
        "identity_client_id",
    ):
        assert field in OUTPUTS
    # The group-connected team and channel stay human-supplied inputs.
    assert 'variable "approval_team_id"' in VARIABLES
    assert 'variable "approval_channel_id"' in VARIABLES


def test_module_requires_https_activity_url() -> None:
    assert 'startswith(var.activity_url, "https://")' in VARIABLES
