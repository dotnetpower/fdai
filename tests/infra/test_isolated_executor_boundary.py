"""Static authority checks for the SD-07 isolated Executor Terraform wiring."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
MAIN = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
VARIABLES = (ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")


def _resource_block(name: str) -> str:
    match = re.search(
        rf'resource "azurerm_role_assignment" "{re.escape(name)}" \{{(?P<body>.*?)\n\}}',
        MAIN,
        re.DOTALL,
    )
    assert match is not None, name
    return match.group("body")


def test_shadow_identity_receives_only_transport_secret_and_pull_roles() -> None:
    expected = {
        "isolated_executor_acr_pull": "AcrPull",
        "isolated_executor_command_receiver": "Azure Event Hubs Data Receiver",
        "isolated_executor_receipt_sender": "Azure Event Hubs Data Sender",
        "isolated_executor_kv_secrets_user": "Key Vault Secrets User",
    }

    for resource_name, role_name in expected.items():
        block = _resource_block(resource_name)
        assert f'role_definition_name = "{role_name}"' in block
        assert "module.isolated_executor_identity[0].principal_id" in block

    shadow_principal_uses = [
        block
        for block in re.findall(
            r'resource "azurerm_role_assignment" "[^"]+" \{.*?\n\}',
            MAIN,
            re.DOTALL,
        )
        if "module.isolated_executor_identity[0].principal_id" in block
    ]
    assert len(shadow_principal_uses) == len(expected)
    assert all(
        forbidden not in "\n".join(shadow_principal_uses)
        for forbidden in (
            "Contributor",
            "Owner",
            "Virtual Machine Contributor",
            "Network Contributor",
        )
    )


def test_shadow_module_uses_operational_transport_and_no_executor_identity() -> None:
    match = re.search(
        r'module "isolated_executor" \{(?P<body>.*?)\n\}',
        MAIN,
        re.DOTALL,
    )
    assert match is not None
    block = match.group("body")

    assert 'source = "./modules/isolated-executor/container-app"' in block
    assert "module.event_bus_auxiliary.kafka_bootstrap" in block
    assert "module.isolated_executor_identity[0].resource_id" in block
    assert "module.identity.resource_id" not in block
    assert "enable_isolated_executor" in block


def test_shadow_deployment_is_opt_in_and_topics_fit_operational_shard() -> None:
    variable = re.search(
        r'variable "enable_isolated_executor" \{(?P<body>.*?)\n\}',
        VARIABLES,
        re.DOTALL,
    )
    assert variable is not None
    assert "default     = false" in variable.group("body")

    operational = re.search(
        r'module "event_bus_auxiliary" \{(?P<body>.*?)\n\}',
        MAIN,
        re.DOTALL,
    )
    assert operational is not None
    block = operational.group("body")
    assert "local.executor_command_topic" in block
    assert "local.executor_receipt_topic" in block


def test_authority_cutover_moves_gateway_and_vertical_identities_from_core() -> None:
    cutover = re.search(
        r'variable "enable_isolated_executor_authority_cutover" \{(?P<body>.*?)\n\}',
        VARIABLES,
        re.DOTALL,
    )
    assert cutover is not None
    assert "default     = false" in cutover.group("body")

    gateway = re.search(
        r'resource "azurerm_function_app_flex_consumption" "dev_gateway" '
        r"\{(?P<body>.*?)\n\}",
        MAIN,
        re.DOTALL,
    )
    assert gateway is not None
    gateway_body = gateway.group("body")
    assert "local.effect_executor_principal_id" in gateway_body
    assert "local.effect_executor_client_id" in gateway_body

    compute = re.search(r'module "compute" \{(?P<body>.*?)\n\}', MAIN, re.DOTALL)
    assert compute is not None
    assert "local.core_vertical_identity_ids" in compute.group("body")

    isolated = re.search(
        r'module "isolated_executor" \{(?P<body>.*?)\n\}',
        MAIN,
        re.DOTALL,
    )
    assert isolated is not None
    assert "local.isolated_executor_vertical_identity_ids" in isolated.group("body")
