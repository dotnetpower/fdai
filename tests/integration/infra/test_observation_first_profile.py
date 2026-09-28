"""Observation-first Terraform defaults and read-only role boundaries."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
VARIABLES = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")


def _variable(name: str) -> str:
    return VARIABLES.split(f'variable "{name}"', maxsplit=1)[1].split(
        "\nvariable ",
        maxsplit=1,
    )[0]


def test_default_product_profile_is_headless_and_has_no_executor_selection() -> None:
    assert '\\"add_ons\\":[]' in _variable("product_profile_json")
    assert '\\"authority_granted\\":false' in _variable("product_profile_json")
    assert "default     = false" in _variable("enable_governed_execution")
    assert "count               = var.enable_governed_execution ? 1 : 0" in MAIN
    assert MAIN.count("count               = var.enable_governed_execution ? 1 : 0") == 3


def test_base_observer_has_reader_and_selected_sources_gate_optional_roles() -> None:
    inventory_reader = MAIN.split(
        'resource "azurerm_role_assignment" "inventory_reader"',
        maxsplit=1,
    )[1].split("resource ", maxsplit=1)[0]
    assert 'role_definition_name = "Reader"' in inventory_reader
    assert "module.inventory_identity.principal_id" in inventory_reader

    for variable, resource in (
        ("enable_inventory_monitoring_reader", "inventory_monitoring_reader"),
        ("enable_inventory_log_analytics_reader", "inventory_log_analytics_reader"),
        ("enable_inventory_cost_management_reader", "inventory_cost_reader"),
    ):
        assert "default     = false" in _variable(variable)
        block = MAIN.split(
            f'resource "azurerm_role_assignment" "{resource}"',
            maxsplit=1,
        )[1].split("resource ", maxsplit=1)[0]
        assert f"count                = var.{variable} ? 1 : 0" in block


def test_observation_identity_receives_no_contributor_or_access_admin_role() -> None:
    inventory_blocks = [
        block
        for block in MAIN.split('resource "azurerm_role_assignment" ')[1:]
        if "module.inventory_identity.principal_id" in block.split("}\n", maxsplit=1)[0]
    ]
    rendered = "\n".join(inventory_blocks)

    assert "Contributor" not in rendered
    assert "User Access Administrator" not in rendered


def test_base_profile_requires_no_azure_policy_assignment() -> None:
    for resource_type in (
        "azurerm_policy_assignment",
        "azurerm_resource_group_policy_assignment",
        "azurerm_subscription_policy_assignment",
    ):
        assert f'resource "{resource_type}"' not in MAIN
