from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LAB_ROOT = REPO_ROOT / "infra" / "scenario-lab"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sre-demo-lab.yml"
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "prepare-runner.sh"
SWEEP_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "run-reference-sweep.sh"
CLEANUP_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "cleanup-runner.sh"
BASH = shutil.which("bash")
assert BASH is not None


def test_scenario_lab_is_an_independent_private_terraform_root() -> None:
    versions = (LAB_ROOT / "versions.tf").read_text(encoding="utf-8")
    network = (LAB_ROOT / "network.tf").read_text(encoding="utf-8")
    aks = (LAB_ROOT / "aks.tf").read_text(encoding="utf-8")
    data_services = (LAB_ROOT / "data-services.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.9"' in versions
    assert 'version = "~> 4.14"' in versions
    assert 'resource "azurerm_resource_group" "scenario_lab"' in (LAB_ROOT / "main.tf").read_text(
        encoding="utf-8"
    )
    assert 'private_endpoint_network_policies = "Disabled"' in network
    assert 'resource "azurerm_nat_gateway" "egress"' in network
    assert 'resource "azurerm_network_security_group" "scenario_lab"' in network
    assert 'resource "azurerm_subnet_network_security_group_association" "scenario_lab"' in network
    assert "private_cluster_enabled" in aks
    assert "local_account_disabled" in aks
    assert "azure_active_directory_role_based_access_control" in aks
    assert "azure_rbac_enabled = true" in aks
    assert 'outbound_type       = "userAssignedNATGateway"' in aks
    assert "node_count                   = 1" in aks
    assert "public_network_access_enabled = false" in data_services
    assert 'private_dns_zone_name = "privatelink.openai.azure.com"' in data_services
    assert "delegated_subnet_id" in data_services
    assert 'name    = "Microsoft.DBforMySQL/flexibleServers"' in network
    assert 'resource "azurerm_network_interface_security_group_association" "stress_vm"' in (
        LAB_ROOT / "vm.tf"
    ).read_text(encoding="utf-8")


def test_scenario_lab_keeps_secrets_out_of_outputs() -> None:
    data_services = (LAB_ROOT / "data-services.tf").read_text(encoding="utf-8")
    outputs = (LAB_ROOT / "outputs.tf").read_text(encoding="utf-8")
    variables = (LAB_ROOT / "variables.tf").read_text(encoding="utf-8")

    assert 'resource "random_password" "mysql_admin"' in data_services
    assert 'resource "azurerm_key_vault_secret" "mysql_admin_password"' in data_services
    assert 'role_definition_name = "Key Vault Secrets Officer"' in data_services
    assert 'output "enforce_environment"' in outputs
    assert "sensitive   = true" in outputs
    assert "random_password.mysql_admin.result" not in outputs
    assert "expires_at_utc" in variables
    assert "expiration_date = var.expires_at_utc" in data_services
    assert "purge_protection_enabled      = true" in data_services
    assert 'name                = "require_secure_transport"' in data_services
    assert 'name                = "tls_version"' in data_services
    assert '"fdai:expires-at" = var.expires_at_utc' in (LAB_ROOT / "main.tf").read_text(
        encoding="utf-8"
    )


def test_scenario_lab_workflow_is_plan_first_and_approval_gated() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    infra_lint = (REPO_ROOT / ".github" / "workflows" / "infra-lint.yml").read_text(
        encoding="utf-8"
    )

    assert "options: [plan, apply, destroy]" in workflow
    assert "default: plan" in workflow
    assert "commit_sha must be an ancestor of protected origin/main" in workflow
    assert "scenario-lab workflow controls differ from protected origin/main" in workflow
    assert (
        "environment: ${{ inputs.action == 'plan' && 'plan-only' || 'scenario-lab' }}" in workflow
    )
    assert "approval_ref is required for a live sweep" in workflow
    assert "enable_vpn_operator_access" in workflow
    assert "SCENARIO_LAB_OPERATOR_PRINCIPAL_ID" in workflow
    assert "DEV_ACCESS_VNET_ID" in workflow
    assert "apply refuses delete or replacement actions" in workflow
    assert 'environment_file="$output_dir/enforce.env"' in workflow
    assert 'environment_file="$(bash' not in workflow
    assert 'CONFIRM_DESTROY" != "destroy-sre-demo-lab"' in workflow
    assert (
        'terraform apply -input=false -auto-approve "$RUNNER_TEMP/sre-demo-lab.tfplan"' in workflow
    )
    assert "terraform destroy" not in workflow
    assert "infra/scenario-lab" in infra_lint
    assert "infra/scenario-lab/backend.tf" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_runner_scripts_fail_before_external_commands_without_authority() -> None:
    prepare = subprocess.run(  # noqa: S603 - fixed repository script and resolved Bash.
        [BASH, str(PREPARE_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    sweep = subprocess.run(  # noqa: S603 - fixed repository script and resolved Bash.
        [BASH, str(SWEEP_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    cleanup = subprocess.run(  # noqa: S603 - fixed repository script and resolved Bash.
        [BASH, str(CLEANUP_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert prepare.returncode == 2
    assert "absolute non-root output directory is required" in prepare.stderr
    assert sweep.returncode == 2
    assert "prepared environment file is required" in sweep.stderr
    assert cleanup.returncode == 2
    assert "existing absolute non-root output directory is required" in cleanup.stderr


def test_live_runner_records_current_approval_reference() -> None:
    runner = (REPO_ROOT / "scripts" / "catalog" / "run-enforce-scenarios.py").read_text(
        encoding="utf-8"
    )
    sweep = SWEEP_SCRIPT.read_text(encoding="utf-8")

    assert 'APPROVAL_REF = _env("FDAI_ENFORCE_APPROVAL_REF")' in runner
    assert 'd["approval_ref"] = APPROVAL_REF' in runner
    assert 'export FDAI_ENFORCE_APPROVAL_REF="$approval_ref"' in sweep
    assert 'SCENARIO_LAB_CONFIRM_ENFORCE:-}" != "true"' in sweep
    assert "helm show chart chaos-mesh/chaos-mesh" in PREPARE_SCRIPT.read_text(encoding="utf-8")


def test_operator_access_is_opt_in_private_and_minimum_role_scoped() -> None:
    variables = (LAB_ROOT / "variables.tf").read_text(encoding="utf-8")
    main = (LAB_ROOT / "main.tf").read_text(encoding="utf-8")
    aks = (LAB_ROOT / "aks.tf").read_text(encoding="utf-8")
    data_services = (LAB_ROOT / "data-services.tf").read_text(encoding="utf-8")
    outputs = (LAB_ROOT / "outputs.tf").read_text(encoding="utf-8")

    assert 'variable "operator_access"' in variables
    assert "default  = null" in variables
    assert 'resource "azurerm_virtual_network_peering" "lab_to_operator"' in main
    assert "use_remote_gateways          = true" in main
    assert 'resource "azurerm_virtual_network_peering" "operator_to_lab"' in main
    assert "allow_gateway_transit        = true" in main
    assert 'role_definition_name = "Monitoring Reader"' in main
    assert 'role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"' in aks
    assert 'role_definition_name = "Key Vault Secrets User"' in data_services
    assert 'output "operator_dns_routing_domains"' in outputs
    assert "public_network_access_enabled = false" in data_services
