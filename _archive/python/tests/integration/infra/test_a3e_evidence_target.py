from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_ROOT = REPO_ROOT / "infra" / "a3e-evidence-target"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_a3e_evidence_target_is_private_separated_and_plan_bound() -> None:
    main = (TARGET_ROOT / "main.tf").read_text(encoding="utf-8")
    outputs = (TARGET_ROOT / "outputs.tf").read_text(encoding="utf-8")
    variables = (TARGET_ROOT / "variables.tf").read_text(encoding="utf-8")
    versions = (TARGET_ROOT / "versions.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.9.0"' in versions
    assert 'version = "~> 4.14"' in versions
    assert 'data "azurerm_resource_group" "target"' in main
    assert 'resource "azurerm_resource_group"' not in main
    assert 'resource "azurerm_public_ip"' not in main
    assert "allow_extension_operations      = false" in main
    assert main.count('resource "azurerm_user_assigned_identity"') == 2
    assert 'resource "azurerm_role_definition" "executor"' in main
    assert '"Microsoft.Compute/virtualMachines/start/action"' in main
    assert '"Microsoft.Compute/virtualMachines/deallocate/action"' in main
    assert 'role_definition_name = "Virtual Machine Contributor"' not in main
    assert 'role_definition_name = "Reader"' in main
    assert main.count("azurerm_linux_virtual_machine.target.id") >= 2
    assert 'source_address_prefix      = "Internet"' in main
    assert 'destination_address_prefix = "Internet"' in main
    assert 'resource "azurerm_subnet_network_security_group_association" "target"' in main
    assert 'resource "azurerm_network_interface_security_group_association" "target"' in main
    assert "depends_on = [azurerm_network_interface_security_group_association.target]" in main
    assert "tags = merge(var.additional_tags, {" in main
    assert "subnet_address_prefix = cidrsubnet(var.vnet_address_space, 3, 0)" in main
    assert 'can(regex("/24$", var.vnet_address_space))' in variables
    assert '"fdai:authority"      = "none"' in main
    assert '"fdai:required-state" = "deallocated"' in main
    assert 'variable "deploy_runner_principal_id"' in variables
    assert 'variable "expires_at_utc"' in variables
    assert 'lower(trimspace(var.vm_image.version)) != "latest"' in variables
    assert 'output "target_contract"' in outputs
    assert "sensitive   = true" in outputs
    assert 'expected_power_state = "deallocated"' in outputs
    assert "effect_authorized    = false" in outputs
    assert "promotion_authorized = false" in outputs


def test_required_ci_validates_the_a3e_evidence_target() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "terraform validate (A3-E evidence target)" in workflow
    assert (
        "terraform -chdir=a3e-evidence-target init -backend=false "
        "-input=false -lockfile=readonly" in workflow
    )
    assert "terraform -chdir=a3e-evidence-target validate" in workflow
