from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MAIN = (_ROOT / "infra" / "bootstrap" / "main.tf").read_text(encoding="utf-8")
_OUTPUTS = (_ROOT / "infra" / "bootstrap" / "outputs.tf").read_text(encoding="utf-8")
_VARIABLES = (_ROOT / "infra" / "bootstrap" / "variables.tf").read_text(encoding="utf-8")


def _resource_body(resource_type: str, name: str) -> str:
    start = f'resource "{resource_type}" "{name}" {{'
    offset = _MAIN.index(start) + len(start)
    depth = 1
    for index in range(offset, len(_MAIN)):
        if _MAIN[index] == "{":
            depth += 1
        elif _MAIN[index] == "}":
            depth -= 1
            if depth == 0:
                return _MAIN[offset:index]
    raise AssertionError(f"unterminated Terraform resource: {resource_type}.{name}")


def test_bootstrap_provisions_and_attaches_stable_deploy_uami() -> None:
    assert 'module "deploy_runner_identity"' in _MAIN
    assert 'name                = "id-${local.suffix}-deploy"' in _MAIN
    vm = _resource_body("azurerm_linux_virtual_machine", "runner")
    assert 'type         = "SystemAssigned, UserAssigned"' in vm
    assert "identity_ids = [module.deploy_runner_identity.resource_id]" in vm


def test_bootstrap_role_manifest_is_exact_and_vm_independent() -> None:
    manifest = _MAIN.split("deploy_runner_role_manifest =", maxsplit=1)[1].split(
        "\n  } : {}", maxsplit=1
    )[0]
    assert set(re.findall(r'role_definition_name = "([^"]+)"', manifest)) == {
        "Contributor",
        "EventGrid Contributor",
        "Network Contributor",
        "Storage Blob Data Contributor",
        "User Access Administrator",
    }

    resources = (
        "runner_app_contributor",
        "runner_app_uaa",
        "runner_ops_network",
        "runner_state_blob",
        "runner_eventgrid_contributor",
    )
    for resource_name in resources:
        body = _resource_body("azurerm_role_assignment", resource_name)
        assert "count                = var.enable_deploy_identity_roles ? 1 : 0" in body
        assert "principal_id         = module.deploy_runner_identity.principal_id" in body
        assert "azurerm_linux_virtual_machine.runner" not in body

    variable = _VARIABLES.split('variable "enable_deploy_identity_roles"', maxsplit=1)[1]
    assert "default     = true" in variable.split("}", maxsplit=1)[0]


def test_bootstrap_exports_both_workflow_identity_coordinates() -> None:
    assert 'output "deploy_runner_client_id"' in _OUTPUTS
    assert "value       = module.deploy_runner_identity.client_id" in _OUTPUTS
    assert 'output "deploy_runner_principal_id"' in _OUTPUTS
    assert "value       = module.deploy_runner_identity.principal_id" in _OUTPUTS
    assert 'output "deploy_runner_role_manifest"' in _OUTPUTS
