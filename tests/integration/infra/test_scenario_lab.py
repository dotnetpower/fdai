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
    main = (LAB_ROOT / "main.tf").read_text(encoding="utf-8")
    variables = (LAB_ROOT / "variables.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.9"' in versions
    assert 'version = "~> 4.14"' in versions
    assert 'data "azurerm_resource_group" "scenario_lab"' in main
    assert 'resource "azurerm_resource_group" "scenario_lab"' not in main
    assert 'variable "resource_group_name"' in variables
    assert 'default     = ["10.73.0.0/20"]' in variables
    assert "10.42." not in variables
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
    assert 'resource "azurerm_private_dns_zone_virtual_network_link" "openai_lab"' in data_services
    assert "private_dns_zone_name = var.azure_openai_private_dns_zone.name" in data_services
    assert 'resource "azurerm_private_endpoint" "azure_openai"' in data_services
    assert "private_dns_zone_ids = [var.azure_openai_private_dns_zone.id]" in data_services
    assert 'module "azure_openai_private_endpoint"' not in data_services
    assert (
        'name                = "${local.unique_suffix}.mysql.database.azure.com"' in data_services
    )
    assert "maintenance_window" not in data_services
    assert "delegated_subnet_id" in data_services
    assert 'name    = "Microsoft.DBforMySQL/flexibleServers"' in network
    assert 'resource "azurerm_network_interface_security_group_association" "stress_vm"' in (
        LAB_ROOT / "vm.tf"
    ).read_text(encoding="utf-8")


def test_scenario_lab_keeps_secrets_inside_the_sensitive_runner_output() -> None:
    data_services = (LAB_ROOT / "data-services.tf").read_text(encoding="utf-8")
    outputs = (LAB_ROOT / "outputs.tf").read_text(encoding="utf-8")
    variables = (LAB_ROOT / "variables.tf").read_text(encoding="utf-8")
    prepare = PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert 'resource "random_password" "mysql_admin"' in data_services
    assert "key_vault" not in data_services
    assert 'output "enforce_environment"' in outputs
    assert "sensitive   = true" in outputs
    assert "mysql_password        = random_password.mysql_admin.result" in outputs
    assert 'output "mysql_password"' not in outputs
    assert "jq -er '.mysql_password'" in prepare
    assert "az keyvault" not in prepare
    assert "expires_at_utc" in variables
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
    assert "SCENARIO_LAB_RESOURCE_GROUP_NAME" in workflow
    assert "SCENARIO_LAB_OPENAI_PRIVATE_DNS_ZONE_ID" in workflow
    assert "SCENARIO_LAB_OPENAI_PRIVATE_DNS_RESOURCE_GROUP_NAME" in workflow
    assert "scenario-lab requires the existing central OpenAI Private DNS zone" in workflow
    assert (
        "SCENARIO_LAB_RUNNER_PRINCIPAL_ID: ${{ vars.SCENARIO_LAB_RUNNER_PRINCIPAL_ID }}" in workflow
    )
    assert "TF_VAR_resource_group_name" in workflow
    assert "DEV_ACCESS_VNET_ID" in workflow
    assert "Grant bounded scenario-lab deployment authority" in workflow
    assert "Revoke bounded scenario-lab deployment authority" in workflow
    assert "raw output remains runner-local" in workflow
    assert "apply refuses delete or replacement actions" in workflow
    assert 'environment_file="$output_dir/enforce.env"' in workflow
    assert 'environment_file="$(bash' not in workflow
    assert 'CONFIRM_DESTROY" != "destroy-sre-demo-lab"' in workflow
    assert workflow.count("terraform apply -input=false -auto-approve") == 3
    assert workflow.count('"$RUNNER_TEMP/sre-demo-lab.tfplan"') >= 3
    assert "terraform destroy" not in workflow
    assert "Quiesce private DNS links before destroy" in workflow
    assert 'select(.type? == "azurerm_private_dns_zone_virtual_network_link")' in workflow
    assert "scenario-lab DNS-link state contains an invalid ARM resource id" in workflow
    assert 'az resource delete --ids "$link_id"' in workflow
    assert 'az resource wait --deleted --ids "$link_id"' in workflow
    assert 'terraform state rm -lock-timeout=5m "$link_address"' in workflow
    assert "scenario-lab DNS recovery refuses a zone with visible VNet links" in workflow
    assert 'link_name="pe-fdai-sre-lab-${TF_VAR_region_short}-oai-runner-link"' in workflow
    assert "az network private-dns link vnet create" in workflow
    assert "az network private-dns link vnet delete" in workflow
    assert "scenario-lab Terraform destroy completed after bounded DNS reconciliation" in workflow
    assert "Verify reference sweep outcomes" in workflow
    assert "(.runs | length) == 10" in workflow
    assert "approval_ref_digest" in workflow
    assert "sre-demo-lab-summary-${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    assert "retention-days: 30" in workflow
    assert "az account show --query user.name" not in workflow
    assert "az account get-access-token" in workflow
    assert "active runner managed identity does not match the configured principal" in workflow
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
    assert 'os.environ.get("FDAI_ENFORCE_REPORT_ROOT")' in runner
    assert "must be an absolute non-root path" in runner
    prepare = PREPARE_SCRIPT.read_text(encoding="utf-8")
    assert "helm show chart chaos-mesh/chaos-mesh" in prepare
    assert "cloud-init status --wait --long" in prepare
    assert "private stress VM cloud-init did not complete" in prepare


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
    assert "additional_user_principal_ids = local.operator_enabled" in data_services
    assert 'output "operator_dns_routing_domains"' in outputs
    assert "private_dns_zone_name = var.azure_openai_private_dns_zone.name" in data_services
