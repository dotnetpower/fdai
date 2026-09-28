from __future__ import annotations

import json
import os
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LAB_ROOT = REPO_ROOT / "infra" / "scenario-lab"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sre-demo-lab.yml"
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "prepare-runner.sh"
COMMERCE_PREPARE_SCRIPT = (
    REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "prepare-commerce.sh"
)
SWEEP_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "run-reference-sweep.sh"
CLEANUP_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "cleanup-runner.sh"
STORE_RENDERER = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "render_aks_store_demo.py"
STORE_DOMAIN_VERIFIER = (
    REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "verify_store_front_domain.py"
)
BASH = shutil.which("bash")
assert BASH is not None


def test_scenario_lab_is_an_independent_public_api_terraform_root() -> None:
    versions = (LAB_ROOT / "versions.tf").read_text(encoding="utf-8")
    network = (LAB_ROOT / "network.tf").read_text(encoding="utf-8")
    aks = (LAB_ROOT / "aks.tf").read_text(encoding="utf-8")
    data_services = (LAB_ROOT / "data-services.tf").read_text(encoding="utf-8")
    main = (LAB_ROOT / "main.tf").read_text(encoding="utf-8")
    variables = (LAB_ROOT / "variables.tf").read_text(encoding="utf-8")
    commerce = (LAB_ROOT / "commerce.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.9"' in versions
    assert 'version = "~> 4.14"' in versions
    assert 'data "azurerm_resource_group" "scenario_lab"' in main
    assert 'resource "azurerm_resource_group" "scenario_lab"' not in main
    assert 'variable "resource_group_name"' in variables
    assert 'default     = ["10.73.0.0/20"]' in variables
    assert "10.42." not in variables
    assert 'private_endpoint_network_policies = "Disabled"' in network
    assert 'resource "azurerm_nat_gateway" "egress"' in network
    assert 'resource "azurerm_servicebus_namespace" "commerce"' in commerce
    assert "local_auth_enabled            = false" in commerce
    assert "public_network_access_enabled = false" in commerce
    assert 'role_definition_name = "Azure Service Bus Data Sender"' in commerce
    assert 'role_definition_name = "Azure Service Bus Data Receiver"' in commerce
    assert 'resource "azurerm_cosmosdb_account" "commerce"' in commerce
    assert "local_authentication_enabled  = false" in commerce
    assert "public_network_access_enabled = false" in commerce
    assert 'resource "azurerm_private_endpoint" "commerce_cosmos"' in commerce
    assert 'resource "azurerm_private_endpoint" "commerce_servicebus"' in commerce
    assert (
        'subject             = "system:serviceaccount:'
        '${var.commerce_namespace}:aks-store-demo"' in commerce
    )
    assert 'variable "commerce_enabled"' in variables
    assert 'resource "azurerm_network_security_group" "scenario_lab"' in network
    assert 'resource "azurerm_subnet_network_security_group_association" "scenario_lab"' in network
    assert "private_endpoints = azurerm_subnet.private_endpoints.id" in network
    assert "aks               = azurerm_subnet.aks.id" not in network
    assert "mysql             = azurerm_subnet.mysql.id" not in network
    assert "stress_vm         = azurerm_subnet.stress_vm.id" not in network
    assert network.count("checkov:skip=CKV2_AZURE_31:Azure Policy attaches") == 3
    assert aks.count("#trivy:ignore:AVD-AZU-0041") == 1
    assert aks.count("#trivy:ignore:AVD-AZU-0065") == 1
    assert aks.count("checkov:skip=CKV_AZURE_6:") == 1
    assert aks.count("checkov:skip=CKV_AZURE_115:") == 1
    assert re.search(r"^\s*private_cluster_enabled\s*=\s*false$", aks, re.MULTILINE)
    assert "private_cluster_public_fqdn_enabled" not in aks
    assert "private_dns_zone_id" not in aks
    assert "api_server_access_profile" not in aks
    assert "api_server_authorized_ip_ranges" not in variables
    assert re.search(r'^\s*name\s*=\s*"aks-store-demo"$', aks, re.MULTILINE)
    assert re.search(r'^\s*dns_prefix\s*=\s*"aks-store-demo"$', aks, re.MULTILINE)
    assert '"aks-${local.suffix}"' not in aks
    assert "local_account_disabled            = true" in aks
    assert "azure_active_directory_role_based_access_control" in aks
    assert "azure_rbac_enabled = true" in aks
    assert 'dynamic "monitor_metrics"' in aks
    assert 'dynamic "web_app_routing"' in aks
    assert 'outbound_type       = "userAssignedNATGateway"' in aks
    assert "node_count                   = 2" in aks
    assert 'upgrade_settings {\n      max_surge = "10%"\n    }' in aks
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
    commerce_prepare = COMMERCE_PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert 'resource "random_password" "mysql_admin"' in data_services
    assert "key_vault" not in data_services
    assert 'output "enforce_environment"' in outputs
    assert "sensitive   = true" in outputs
    assert "mysql_password        = random_password.mysql_admin.result" in outputs
    assert 'output "mysql_password"' not in outputs
    assert "jq -er '.mysql_password'" in prepare
    assert "az keyvault" not in prepare
    assert "queuePassword" not in commerce_prepare
    assert "ORDER_DB_PASSWORD" not in commerce_prepare
    assert "useAzureAd=true" in commerce_prepare
    assert "expires_at_utc" in variables
    assert 'name                = "require_secure_transport"' in data_services
    assert 'name                = "tls_version"' in data_services
    assert '"fdai:expires-at" = var.expires_at_utc' in (LAB_ROOT / "main.tf").read_text(
        encoding="utf-8"
    )


def test_commerce_profile_exposes_only_https_storefront() -> None:
    prepare = COMMERCE_PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert "61b033448904a930f01d497ce7139aca87a1b12d" in prepare
    assert "--set storeFront.serviceType=ClusterIP" in prepare
    assert "--set storeAdmin.serviceType=ClusterIP" in prepare
    assert 'ingressClassName: "webapprouting.kubernetes.azure.com"' in prepare
    assert '"https://$storefront_hostname"' in prepare
    assert "--proto '=https'" in prepare
    assert "protect-store-admin" in prepare
    assert "product-service-monitor.yaml" in prepare
    assert "crd/servicemonitors.azmonitoring.coreos.com" in prepare
    assert "SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_REF" in prepare
    assert "SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_EXPIRES_AT" in prepare
    assert (
        subprocess.run(  # noqa: S603 - fixed repository script and resolved Bash.
            [BASH, "-n", str(COMMERCE_PREPARE_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def test_scenario_lab_renders_the_pinned_aks_store_demo_domain() -> None:
    renderer = runpy.run_path(str(STORE_RENDERER))
    render_manifest = renderer["render_manifest"]
    replacements = renderer["IMAGE_REPLACEMENTS"]
    order_source = renderer["ORDER_SERVICE_REPLICA_SOURCE"]
    store_front_source = renderer["STORE_FRONT_METADATA_SOURCE"]
    store_admin_source = renderer["STORE_ADMIN_SERVICE_SOURCE"]

    source = (
        order_source
        + "\n"
        + "\n".join(f"image: {image}" for image in replacements)
        + "\n"
        + store_front_source
        + "  type: LoadBalancer\n"
        + store_admin_source
    )
    rendered = render_manifest(source, "fdai-store-lab-krc-abc123")

    assert "replicas: 3" in rendered
    assert "replicas: 1" not in rendered
    assert rendered.count("type: LoadBalancer") == 1
    assert rendered.count("type: ClusterIP") == 1
    assert (
        'service.beta.kubernetes.io/azure-dns-label-name: "fdai-store-lab-krc-abc123"' in rendered
    )
    for tagged_image, digest_image in replacements.items():
        assert tagged_image not in rendered
        assert f"image: {digest_image}" in rendered


def test_scenario_lab_store_domain_verifier_checks_dns_and_health(monkeypatch) -> None:
    verifier = runpy.run_path(str(STORE_DOMAIN_VERIFIER))
    verify = verifier["verify"]
    monkeypatch.setitem(
        verify.__globals__,
        "_resolved_addresses",
        lambda hostname: {"203.0.113.10"},
    )
    monkeypatch.setitem(verify.__globals__, "_healthy", lambda hostname: True)

    assert verify("fdai-store-lab-krc-abc123.koreacentral.cloudapp.azure.com", "203.0.113.10")


def test_scenario_lab_prepares_store_demo_as_the_fault_target() -> None:
    prepare = PREPARE_SCRIPT.read_text(encoding="utf-8")
    outputs = (LAB_ROOT / "outputs.tf").read_text(encoding="utf-8")
    main = (LAB_ROOT / "main.tf").read_text(encoding="utf-8")
    renderer = STORE_RENDERER.read_text(encoding="utf-8")

    assert 'SOURCE_COMMIT = "61b033448904a930f01d497ce7139aca87a1b12d"' in renderer
    assert (
        'SOURCE_SHA256 = "c290390edb7e26396a498dd5cbcf7ace94115fe4be813cd80f4fda69d6cbcfee"'
        in renderer
    )
    assert len(re.findall(r"@sha256:[0-9a-f]{64}", renderer)) == 10
    assert (
        'render_aks_store_demo.py" \\\n  "$store_manifest" \\\n  "$store_front_dns_label"'
        in prepare
    )
    assert "verify_store_front_domain.py" in prepare
    assert "service/store-front" in prepare
    assert "store-front-url" in prepare
    assert "FDAI_STORE_FRONT_URL" in prepare
    assert "create deployment api-backend" not in prepare
    assert "rollout status statefulset/documentdb" in prepare
    assert "rollout status statefulset/rabbitmq" in prepare
    assert "wait --for=condition=available deployment" in prepare
    assert "FDAI_ENFORCE_BACKEND_CONTAINER" in prepare
    assert "FDAI_ENFORCE_BACKEND_REPLICAS" in prepare
    assert "FDAI_ENFORCE_BACKEND_IMAGE" in prepare
    assert 'backend_deployment    = "order-service"' in outputs
    assert 'backend_service       = "order-service"' in outputs
    assert 'backend_label         = "app=order-service"' in outputs
    assert 'backend_container     = "order-service"' in outputs
    assert "backend_replicas      = 3" in outputs
    assert 'store_front_dns_label    = "fdai-store-${var.environment}-${var.region_short}-' in main
    assert 'store_front_dns_hostname = "${local.store_front_dns_label}.${var.region}' in main
    assert "store_front_dns_label = local.store_front_dns_label" in outputs
    assert "store_front_hostname  = local.store_front_dns_hostname" in outputs


def test_scenario_lab_workflow_is_plan_first_and_approval_gated() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "options: [plan, destroy-plan, apply, recreate-aks, destroy]" in workflow
    assert "default: plan" in workflow
    assert "Checkout protected workflow verifier" in workflow
    assert "workflow-path: .github/workflows/sre-demo-lab.yml" in workflow
    assert "inputs.action == 'plan' || inputs.action == 'destroy-plan'" in workflow
    assert "'plan-only' || 'scenario-lab'" in workflow
    assert "approval_ref is required for a live sweep" in workflow
    assert "scenario_id:" in workflow
    assert "SCENARIO_LAB_SCENARIO_ID: ${{ inputs.scenario_id }}" in workflow
    assert "enable_vpn_operator_access" in workflow
    assert "SCENARIO_LAB_OPERATOR_PRINCIPAL_ID" in workflow
    assert "SCENARIO_LAB_RESOURCE_GROUP_NAME" in workflow
    assert "SCENARIO_LAB_OPENAI_PRIVATE_DNS_ZONE_ID" in workflow
    assert "SCENARIO_LAB_OPENAI_PRIVATE_DNS_RESOURCE_GROUP_NAME" in workflow
    assert "scenario-lab requires the existing central OpenAI Private DNS zone" in workflow
    assert "DEPLOY_RUNNER_PRINCIPAL_ID: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
    assert 'ARM_USE_MSI: "true"' in workflow
    assert "ARM_CLIENT_ID: ${{ vars.DEPLOY_RUNNER_CLIENT_ID }}" in workflow
    assert (
        "SCENARIO_LAB_RUNNER_PRINCIPAL_ID: ${{ vars.SCENARIO_LAB_RUNNER_PRINCIPAL_ID }}" in workflow
    )
    assert "TF_VAR_resource_group_name" in workflow
    assert "SCENARIO_LAB_AKS_API_AUTHORIZED_IP_RANGES" not in workflow
    assert (
        "TF_VAR_aks_node_vm_size: "
        "${{ vars.SCENARIO_LAB_AKS_NODE_VM_SIZE || 'Standard_D2s_v5' }}" in workflow
    )
    assert (
        "TF_VAR_stress_vm_size: "
        "${{ vars.SCENARIO_LAB_STRESS_VM_SIZE || 'Standard_B2s' }}" in workflow
    )
    assert "SCENARIO_LAB_BACKEND_IMAGE" not in workflow
    assert "Configure AKS test substrate" in workflow
    assert "Verify running AKS target" in workflow
    assert "Start stopped AKS sweep target" not in workflow
    assert 'cluster_name="$(terraform output -raw aks_cluster_name)"' in workflow
    assert '[[ "$cluster_name" == "aks-store-demo" ]]' in workflow
    assert '"$RUNNER_TEMP/sre-demo-lab-aks-started-by-run"' in workflow
    assert "Restore AKS power state" in workflow
    assert "timeout 900 az aks start" in workflow
    assert "timeout 900 az aks stop" in workflow
    assert "printf 'store_front_url=%s\\n' \"$store_front_url\"" in workflow
    assert "AKS Store Demo: %s" in workflow
    assert "DEV_ACCESS_VNET_ID" in workflow
    assert "Grant bounded scenario-lab deployment authority" in workflow
    assert "Revoke bounded scenario-lab deployment authority" in workflow
    assert "Resolve bounded operator network scope" in workflow
    assert "configured operator VNet id is outside the active subscription" in workflow
    assert "configured operator VNet does not resolve to the exact requested scope" in workflow
    assert "Grant bounded operator network authority" in workflow
    assert '--role "Network Contributor"' in workflow
    assert '--scope "$OPERATOR_VNET_ID"' in workflow
    assert "Wait for bounded authority propagation" in workflow
    assert "readonly authority_deadline_seconds=300" in workflow
    assert "readonly authority_retry_seconds=15" in workflow
    assert "readonly authority_deadline=$((SECONDS + authority_deadline_seconds))" in workflow
    assert "local deadline=$((SECONDS + authority_deadline_seconds))" not in workflow
    assert "Microsoft.Authorization/permissions?api-version=2022-04-01" in workflow
    assert 'wait_for_effective_action "$RESOURCE_GROUP_ID" "*"' in workflow
    assert '"$OPERATOR_VNET_ID" "Microsoft.Network/*"' in workflow
    assert "authority did not become effective within five minutes" in workflow
    assert 'echo "$permissions"' not in workflow
    assert "Revoke bounded operator network authority" in workflow
    assert "steps.operator-network-authority.outputs.remove_after_run == 'true'" in workflow
    assert "Install checksum-pinned kubelogin" in workflow
    assert "KUBELOGIN_VERSION: v0.2.19" in workflow
    assert (
        "KUBELOGIN_LINUX_AMD64_SHA256: "
        "ebaeff02aa899c5cae6a2b954b64fc02738185319df2570f7dc053451efa4b2f" in workflow
    )
    assert "Install checksum-pinned kubectl" in workflow
    assert "KUBECTL_VERSION: v1.31.14" in workflow
    assert (
        "KUBECTL_LINUX_AMD64_SHA256: "
        "8791ec7c8966b61420d55103a5fb948de9f0ca3d7306d789734975ad9704bdb0" in workflow
    )
    assert '"https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"' in workflow
    assert "required kubectl installer command is unavailable" in workflow
    assert '"$tool_dir/kubectl" version --client=true' in workflow
    assert "Install checksum-pinned Helm" in workflow
    assert "HELM_VERSION: v3.18.6" in workflow
    assert (
        "HELM_LINUX_AMD64_SHA256: "
        "3f43c0aa57243852dd542493a0f54f1396c0bc8ec7296bbb2c01e802010819ce" in workflow
    )
    assert '"https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz"' in workflow
    assert "required Helm installer command is unavailable" in workflow
    assert '"$tool_dir/helm" version --short' in workflow
    assert "sha256sum --check --status" in workflow
    assert "--connect-timeout 10 --max-time 120" in workflow
    assert "--retry 2 --retry-delay 2 --retry-all-errors --retry-max-time 120" in workflow
    assert "required kubelogin installer command is unavailable" in workflow
    assert 'trap \'rm -rf -- "$archive" "$extract_dir"\' EXIT' in workflow
    assert "for command_name in az helm jq kubectl kubelogin python3 terraform timeout" in workflow
    assert "Adopt succeeded partial-apply network resources" in workflow
    assert "Recover healthy partial workspace state" in workflow
    assert 'terraform state pull >"$state_snapshot"' in workflow
    assert 'select(.status == "tainted")' in workflow
    assert "Scenario workspace recovery requires exactly one tainted state instance." in workflow
    assert "Tainted workspace state does not match the exact scenario-lab resource." in workflow
    assert "az monitor log-analytics workspace show" in workflow
    assert '.provisioningState == "Succeeded"' in workflow
    assert '.sku.name == "PerGB2018"' in workflow
    assert ".retentionInDays == 30" in workflow
    assert ".workspaceCapping.dailyQuotaGb == 1" in workflow
    assert '.tags["fdai:managed"] == "true"' in workflow
    assert '.tags["fdai:layer"] == "scenario-lab"' in workflow
    assert 'terraform untaint -lock-timeout=5m "$workspace_address"' in workflow
    assert "sre-demo-lab-recovery-state.json" in workflow
    assert "scenario-lab partial-resource adoption rejected an invalid resource id" in workflow
    assert (
        "scenario-lab partial-resource adoption failed; raw output remains runner-local" in workflow
    )
    assert "terraform import -input=false -lock-timeout=5m" in workflow
    assert 'terraform state list >"$state_list"' in workflow
    assert 'grep -Fxq "$address" "$state_list"' in workflow
    assert 'terraform state list | grep -Fxq "$address"' not in workflow
    assert 'printf \'%s\\n\' "$address" >>"$state_list"' in workflow
    assert "azurerm_virtual_network_peering.lab_to_operator[0]" in workflow
    assert "azurerm_virtual_network_peering.operator_to_lab[0]" in workflow
    assert "azurerm_private_dns_zone_virtual_network_link.mysql_operator[0]" in workflow
    assert "raw output remains runner-local" in workflow
    assert "Terraform apply diagnostic addresses:" in workflow
    assert "Terraform apply diagnostic Azure codes:" in workflow
    assert "Terraform destroy diagnostic addresses:" in workflow
    assert "Terraform destroy diagnostic Azure codes:" in workflow
    assert 'print_destroy_diagnostic "$destroy_log"' in workflow
    assert 'print_destroy_diagnostic "$retry_log"' in workflow
    assert 'print_apply_diagnostic "$RUNNER_TEMP/sre-demo-lab-apply.log"' in workflow
    assert "Terraform plan diagnostic categories:" in workflow
    assert "Terraform plan diagnostic addresses:" in workflow
    assert "Terraform plan diagnostic Azure codes:" in workflow
    assert 'print_plan_diagnostic "$plan_log"' in workflow
    assert 'cat "$RUNNER_TEMP/sre-demo-lab-apply.log"' not in workflow
    assert 'cat "$plan_log"' not in workflow
    assert "apply refuses delete or replacement actions" in workflow
    assert 'CONFIRM_AKS_RECREATION" != "recreate-aks-store-demo"' in workflow
    assert "recreate-aks requires replacement of the exact scenario-lab cluster" in workflow
    assert "recreate-aks replacement is not limited to the reviewed private API fields" in workflow
    assert "recreate-aks plan contains a destructive address outside the allowlist" in workflow
    assert 'azurerm_kubernetes_cluster.scenario_lab" and' in workflow
    assert '($paths | index("private_dns_zone_id")) != null' in workflow
    assert "azurerm_role_assignment.runner_aks_credentials" in workflow
    assert "azurerm_role_assignment.runner_aks_admin" in workflow
    assert '"field\\t\\($address)\\t\\($path | map(tostring) | join("."))"' in workflow
    assert '"replace-path\\t\\($address)\\t\\(map(tostring) | join("."))"' in workflow
    assert "(.change.replace_paths // [])[]?" in workflow
    assert '"before_value"' not in workflow
    assert '"after_value"' not in workflow
    assert 'environment_file="$output_dir/enforce.env"' in workflow
    assert 'environment_file="$(bash' not in workflow
    assert 'CONFIRM_DESTROY" != "destroy-sre-demo-lab"' in workflow
    assert workflow.count("inputs.action != 'destroy-plan'") == 7
    assert "terraform apply -input=false -auto-approve" not in workflow
    assert workflow.count("terraform apply -json -input=false -auto-approve") == 3
    assert workflow.count("terraform apply -json -input=false -auto-approve -parallelism=2") == 1
    assert workflow.count('"$RUNNER_TEMP/sre-demo-lab.tfplan"') >= 3
    assert "terraform destroy" not in workflow
    assert (
        '[[ "$REQUESTED_ACTION" == "destroy" || "$REQUESTED_ACTION" == "destroy-plan" ]]'
        in workflow
    )
    assert "plan_args=(-destroy -refresh=false)" in workflow
    assert "Quiesce private DNS links before destroy" in workflow
    assert 'select(.type == "azurerm_private_dns_zone_virtual_network_link")' in workflow
    assert "scenario-lab DNS-link state contains an invalid ARM resource id" in workflow
    assert 'az resource delete --ids "$link_id"' in workflow
    assert 'az resource wait --deleted --ids "$link_id"' in workflow
    assert 'terraform state rm -lock-timeout=5m "$link_address"' in workflow
    assert "for configuration in require_secure_transport tls_version" in workflow
    assert 'address="azurerm_mysql_flexible_server_configuration.${configuration}"' in workflow
    assert "scenario-lab MySQL configuration recovery requires the parent server" in workflow
    assert 'terraform state rm -lock-timeout=5m "$address"' in workflow
    assert "scenario-lab DNS recovery refuses a zone with visible VNet links" in workflow
    assert "scenario-lab DNS recovery requires the Terraform-owned lab VNet" in workflow
    assert 'link_name="pe-fdai-sre-lab-${TF_VAR_region_short}-oai-runner-link"' in workflow
    assert '--virtual-network "$lab_vnet_id"' in workflow
    assert "az network private-dns link vnet create" in workflow
    assert "az network private-dns link vnet delete" in workflow
    assert "scenario-lab Terraform destroy completed after bounded DNS reconciliation" in workflow
    assert "Verify reference sweep outcomes" in workflow
    assert "expected_runs=10" in workflow
    assert "expected_runs=1" in workflow
    assert "(.runs | length) == $expected_runs" in workflow
    assert "approval_ref_digest" in workflow
    assert "sre-demo-lab-summary-${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    assert "retention-days: 30" in workflow
    assert "az account show --query user.name" not in workflow
    assert "login-deploy-identity.sh" in workflow
    assert "terraform -chdir=scenario-lab validate" in ci_workflow
    assert "infra/scenario-lab/backend.tf" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_scenario_lab_apply_diagnostic_projects_only_allowlisted_tokens(tmp_path: Path) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script_match = re.search(
        r'python3 - "\$1" <<\'PY\'\n(?P<script>.*?)\n          PY',
        workflow,
        re.DOTALL,
    )
    assert script_match is not None
    script = "\n".join(
        line.removeprefix("          ") for line in script_match.group("script").splitlines()
    )
    raw_log = tmp_path / "apply.log"
    raw_log.write_text(
        '{"type":"apply_errored","@message":"private deployment value",'
        '"hook":{"resource":{"addr":"azurerm_virtual_network_peering.lab_to_operator[0]"}}}\n'
        '{"type":"diagnostic","diagnostic":{"severity":"error",'
        '"address":"azurerm_virtual_network_peering.lab_to_operator[0]",'
        '"detail":"Code=RemoteGatewayNotReady Message=private deployment value '
        '/subscriptions/private/resourceGroups/private"}}\n'
        '{"type":"apply_errored","hook":{"resource":{"addr":'
        '"azurerm_subnet_network_security_group_association.scenario_lab[\\"aks\\"]"}}}\n'
        '{"type":"outputs","outputs":{"secret":{"sensitive":true,"value":"private"}}}\n',
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - fixed interpreter and extracted repository script.
        [sys.executable, "-", str(raw_log)],
        input=script,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "azurerm_virtual_network_peering.lab_to_operator[0]" in result.stdout
    assert 'azurerm_subnet_network_security_group_association.scenario_lab["aks"]' in result.stdout
    assert "RemoteGatewayNotReady" in result.stdout
    assert "private deployment value" not in result.stdout
    assert "/subscriptions/" not in result.stdout
    assert "resourceGroups" not in result.stdout


def _plan_diagnostic_output(tmp_path: Path, lines: list[object]) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script_match = re.search(
        r'python3 - "\$1" <<\'PY_PLAN\'\n(?P<script>.*?)\n          PY_PLAN',
        workflow,
        re.DOTALL,
    )
    assert script_match is not None
    script = "\n".join(
        line.removeprefix("          ") for line in script_match.group("script").splitlines()
    )
    raw_log = tmp_path / "plan.log"
    raw_log.write_text(
        "".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines),
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - fixed interpreter and extracted repository script.
        [sys.executable, "-", str(raw_log)],
        input=script,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return result.stdout


LEAKED_ROLE_ASSIGNMENT_ID = (
    "/subscriptions/leak-subscription/resourceGroups/leak-group/providers/"
    "Microsoft.ContainerService/managedClusters/leak-cluster/providers/"
    "Microsoft.Authorization/roleAssignments/leak-assignment"
)
PLAN_PROGRESS_LINES: list[object] = [
    {"@level": "info", "@message": "Terraform 1.9.8", "type": "version"},
    {
        "@level": "info",
        "@message": (
            "azurerm_role_assignment.runner_aks_admin: Refreshing state... "
            f"[id={LEAKED_ROLE_ASSIGNMENT_ID}]"
        ),
        "type": "refresh_start",
        "hook": {
            "resource": {"addr": "azurerm_role_assignment.runner_aks_admin"},
            "id_key": "id",
            "id_value": LEAKED_ROLE_ASSIGNMENT_ID,
        },
    },
    {
        "@level": "info",
        "@message": "authorization audit is not authorized for leak-cluster",
        "type": "log",
        "diagnostic": {"severity": "error", "summary": "authorization for leak-cluster"},
    },
    {
        "@level": "warn",
        "@message": "Warning: Argument is deprecated",
        "type": "diagnostic",
        "diagnostic": {
            "severity": "warning",
            "summary": "Argument is deprecated",
            "detail": (
                "Azure authorization for leak-cluster timed out; the client is not authorized."
            ),
            "address": "azurerm_role_assignment.runner_aks_admin",
        },
    },
    "Error: plain text for leak-cluster was not authorized by Microsoft.Authorization",
]


def test_scenario_lab_plan_diagnostic_ignores_refresh_and_progress_text(tmp_path: Path) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    stdout = _plan_diagnostic_output(tmp_path, PLAN_PROGRESS_LINES)

    assert 'terraform plan -json "${plan_args[@]}" -input=false -lock-timeout=5m' in workflow
    assert 'terraform show -json "$plan_file" >"$RUNNER_TEMP/sre-demo-lab-plan.json"' in workflow
    assert stdout == (
        "Terraform plan diagnostic errors: 0\n"
        "Terraform plan diagnostic categories: unclassified\n"
        "Terraform plan diagnostic addresses: unavailable\n"
        "Terraform plan diagnostic Azure codes: unavailable\n"
    )


def test_scenario_lab_plan_diagnostic_projects_only_allowlisted_tokens(tmp_path: Path) -> None:
    error_lines: list[object] = [
        {
            "@level": "error",
            "@message": "Error: leak-message timed out",
            "type": "diagnostic",
            "diagnostic": {
                "severity": "error",
                "summary": 'retrieving Deployment (Subscription: "leak-subscription")',
                "detail": (
                    "unexpected status 403 (403 Forbidden) with error: AuthorizationFailed: "
                    "The client 'leak-client' with object id 'leak-object' does not have "
                    "authorization to perform action over scope "
                    f"'{LEAKED_ROLE_ASSIGNMENT_ID}'"
                ),
                "address": (
                    'module.azure_openai.azurerm_cognitive_deployment.capability["sre-rate-limit"]'
                ),
                "snippet": {"code": "leak-snippet", "values": [{"statement": "is leak-value"}]},
            },
        },
        {
            "type": "diagnostic",
            "diagnostic": {
                "severity": "error",
                "summary": "reading Resource Group leak-group",
                "detail": (
                    'Status=404 Code="ResourceGroupNotFound" '
                    "Message=\"Resource group 'leak-group' could not be found.\""
                ),
                "address": "data.azurerm_resource_group.scenario_lab",
            },
        },
        {
            "type": "diagnostic",
            "diagnostic": {
                "severity": "error",
                "summary": "updating Subnet leak-subnet",
                "detail": (
                    "RESPONSE 403: 403 Forbidden\nERROR CODE: RequestDisallowedByPolicy\n"
                    '{"error":{"code":"RequestDisallowedByPolicy","message":"leak-policy"}}'
                ),
                "address": (
                    'azurerm_subnet_network_security_group_association.scenario_lab["private_endpoints"]'
                ),
            },
        },
        {
            "type": "diagnostic",
            "diagnostic": {
                "severity": "error",
                "summary": "Error acquiring the state lock",
                "detail": "Lock Info: ID: leak-lock",
                "address": (
                    "azurerm_kubernetes_cluster.scenario_lab /subscriptions/leak-subscription"
                ),
            },
        },
        {
            "type": "diagnostic",
            "diagnostic": {
                "severity": "error",
                "summary": "Resource precondition failed",
                "detail": "The authenticated Terraform principal must match leak-principal.",
            },
        },
    ]

    stdout = _plan_diagnostic_output(tmp_path, [*PLAN_PROGRESS_LINES, *error_lines])

    assert stdout == (
        "Terraform plan diagnostic errors: 5\n"
        "Terraform plan diagnostic categories: authentication, authorization, condition_failed, "
        "provider_read, request_disallowed_by_policy, resource_not_found, state_lock\n"
        "Terraform plan diagnostic addresses: "
        'azurerm_subnet_network_security_group_association.scenario_lab["private_endpoints"], '
        "data.azurerm_resource_group.scenario_lab, "
        'module.azure_openai.azurerm_cognitive_deployment.capability["sre-rate-limit"]\n'
        "Terraform plan diagnostic Azure codes: AuthorizationFailed, HTTP403, HTTP404, "
        "RequestDisallowedByPolicy, ResourceGroupNotFound\n"
    )
    assert "leak" not in stdout
    assert "/subscriptions/" not in stdout
    assert "Microsoft.Authorization" not in stdout
    assert "timeout" not in stdout


@pytest.mark.parametrize(
    ("summary", "detail", "category"),
    [
        (
            "Failed to query available provider packages",
            "Could not retrieve the list of available versions for provider hashicorp/azurerm",
            "provider_installation",
        ),
        ("Failed to load plugin schemas", "Error while loading schemas", "provider_installation"),
        ("Inconsistent dependency lock file", "", "provider_installation"),
        ("Error loading state: blob leak-blob", "", "backend_state"),
        ("Failed to get existing workspaces", "containers leak-container", "backend_state"),
        ("Failed to persist state to backend", "", "backend_state"),
        ("Error acquiring the state lock", "Lock Info: ID: leak-lock", "state_lock"),
        ("Invalid provider configuration", "", "provider_configuration"),
        (
            "building account: could not acquire access token to parse claims",
            "",
            "provider_configuration",
        ),
        (
            "unable to build authorizer for Resource Manager API",
            "could not configure MSI Authorizer: leak-endpoint",
            "provider_configuration",
        ),
        (
            "building account",
            "ManagedIdentityCredential: failed to request token from metadata endpoint",
            "authentication",
        ),
        (
            "Unsupported argument",
            'An argument named "leak" is not expected here.',
            "unsupported_attribute",
        ),
        ("Unsupported block type", "", "unsupported_attribute"),
        ("Unsupported attribute", "", "unsupported_attribute"),
        (
            "Invalid index",
            "The given key does not identify an element.",
            "invalid_configuration_value",
        ),
        ("Incorrect attribute value type", "", "invalid_configuration_value"),
        ("Invalid for_each argument", "", "invalid_configuration_value"),
        ("Reference to undeclared input variable", "", "reference_error"),
        ("Invalid reference", "", "reference_error"),
        ("Reference to undeclared resource", "", "reference_to_undeclared_resource"),
        ("Invalid value for variable", "leak-variable validation", "invalid_input_variable"),
        ("No value for required variable", "", "missing_input_variable"),
        ("Provider produced invalid plan", "", "provider_inconsistency"),
        ("Plugin did not respond", "", "plugin_failure"),
        ("Request cancelled", "", "plugin_failure"),
        (
            "retrieving Kubernetes Cluster",
            "dial tcp: lookup leak-host: no such host",
            "network",
        ),
        ("retrieving Kubernetes Cluster", "context deadline exceeded", "timeout"),
        (
            "creating Deployment",
            "Code=MissingSubscriptionRegistration",
            "subscription_not_registered",
        ),
    ],
)
def test_scenario_lab_plan_diagnostic_classifies_terraform_error_summaries(
    tmp_path: Path, summary: str, detail: str, category: str
) -> None:
    line = {
        "@level": "error",
        "@message": f"Error: {summary}",
        "type": "diagnostic",
        "diagnostic": {"severity": "error", "summary": summary, "detail": detail},
    }

    stdout = _plan_diagnostic_output(tmp_path, [*PLAN_PROGRESS_LINES, line])
    categories = stdout.splitlines()[1].removeprefix("Terraform plan diagnostic categories: ")

    assert stdout.splitlines()[0] == "Terraform plan diagnostic errors: 1"
    assert category in categories.split(", ")
    assert "leak" not in stdout


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


@pytest.mark.parametrize(
    ("driver", "reason"),
    [
        ("measure-detection-latency.py", "raw_injection_driver_retired"),
    ],
)
def test_raw_reference_drivers_refuse_live_runs_until_ported(driver: str, reason: str) -> None:
    script = REPO_ROOT / "scripts" / "catalog" / driver
    result = subprocess.run(  # noqa: S603 - fixed repository script and interpreter.
        [sys.executable, str(script), "aks-pod-kill"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", "")},
    )

    refusal = json.loads(result.stderr)
    assert result.returncode == 3
    assert refusal["outcome"] == "refused"
    assert refusal["reason"] == reason
    assert refusal["mutation_attempted"] is False
    assert "GovernedChaosExecutionAdapter" in refusal["detail"]
    assert result.stdout == ""


def test_the_retired_raw_reference_sweep_driver_is_gone() -> None:
    assert not (REPO_ROOT / "scripts" / "catalog" / "run-enforce-scenarios.py").exists()


def test_reference_sweep_runs_only_through_the_governed_runner() -> None:
    sweep = SWEEP_SCRIPT.read_text(encoding="utf-8")

    assert "scripts/catalog/run-catalog-scenario.py" in sweep
    assert "run-enforce-scenarios.py" not in sweep
    assert "scenario_args=(--run-sweep)" in sweep
    assert 'scenario_args=(--run "$scenario_id")' in sweep
    assert "--confirm-enforce" in sweep


def test_reference_sweep_pins_the_measured_report_where_the_workflow_reads_it() -> None:
    sweep = SWEEP_SCRIPT.read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "sre-demo-lab.yml").read_text(
        encoding="utf-8"
    )

    assert 'report_root="${FDAI_ENFORCE_REPORT_ROOT:-}"' in sweep
    assert 'scenario_args+=(--measured-report "$report_root/report.json")' in sweep
    assert 'report="$FDAI_ENFORCE_REPORT_ROOT/report.json"' in workflow
    assert '.outcome == "validated" and .detected == true and .reverted == true' in workflow


def test_reference_sweep_passes_the_current_approval_claim() -> None:
    sweep = SWEEP_SCRIPT.read_text(encoding="utf-8")

    assert 'export FDAI_ENFORCE_APPROVAL_REF="$approval_ref"' in sweep
    assert 'SCENARIO_LAB_CONFIRM_ENFORCE:-}" != "true"' in sweep
    assert "SCENARIO_LAB_SCENARIO_ID:-all" in sweep
    prepare = PREPARE_SCRIPT.read_text(encoding="utf-8")
    assert "helm show chart chaos-mesh/chaos-mesh" in prepare
    assert "az helm jq kubectl kubelogin python3 terraform" in prepare
    # The lab API is public; Azure rejects --public-fqdn for a cluster that is not private.
    assert "--public-fqdn" not in prepare
    assert 'resource_group="$(jq -er \'.resource_group\' <<<"$terraform_output")"' in prepare
    assert 'aks_cluster_name="$(jq -er \'.aks_cluster_name\' <<<"$terraform_output")"' in prepare
    assert (
        "az aks get-credentials \\\n"
        '  --resource-group "$resource_group" \\\n'
        '  --name "$aks_cluster_name" \\\n'
        '  --file "$kubeconfig" \\\n'
        "  --overwrite-existing \\\n"
        "  --only-show-errors\n"
    ) in prepare
    assert "--admin" not in prepare
    assert 'kubelogin convert-kubeconfig --kubeconfig "$kubeconfig" -l msi' in prepare
    assert "-l devicecode" not in prepare
    assert "readonly vm_run_command_max_attempts=20" in prepare
    assert "readonly vm_run_command_retry_seconds=15" in prepare
    assert "readonly vm_run_command_deadline_seconds=300" in prepare
    assert 'timeout --foreground "${remaining_seconds}s" az vm run-command invoke' in prepare
    assert "(AuthorizationFailed" in prepare
    assert "readiness authorization did not propagate within five minutes" in prepare
    assert 'echo "$command_output"' not in prepare
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
    assert "depends_on = [azurerm_virtual_network_peering.operator_to_lab]" in main
    assert "use_remote_gateways          = true" in main
    assert 'resource "azurerm_virtual_network_peering" "operator_to_lab"' in main
    assert "allow_gateway_transit        = true" in main
    assert 'role_definition_name = "Monitoring Reader"' in main
    assert 'role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"' in aks
    assert "additional_user_principal_ids = local.operator_enabled" in data_services
    assert 'output "operator_dns_routing_domains"' in outputs
    assert "private_dns_zone_name = var.azure_openai_private_dns_zone.name" in data_services
