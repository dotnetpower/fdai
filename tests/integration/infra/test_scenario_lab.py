from __future__ import annotations

import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LAB_ROOT = REPO_ROOT / "infra" / "scenario-lab"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sre-demo-lab.yml"
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "prepare-runner.sh"
SWEEP_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "run-reference-sweep.sh"
CLEANUP_SCRIPT = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "cleanup-runner.sh"
STORE_RENDERER = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "render_aks_store_demo.py"
STORE_DOMAIN_VERIFIER = (
    REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "verify_store_front_domain.py"
)
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

    assert "options: [plan, apply, destroy]" in workflow
    assert "default: plan" in workflow
    assert "Checkout protected workflow verifier" in workflow
    assert "workflow-path: .github/workflows/sre-demo-lab.yml" in workflow
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
    assert "DEPLOY_RUNNER_PRINCIPAL_ID: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
    assert (
        "SCENARIO_LAB_RUNNER_PRINCIPAL_ID: ${{ vars.SCENARIO_LAB_RUNNER_PRINCIPAL_ID }}" in workflow
    )
    assert "TF_VAR_resource_group_name" in workflow
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
    assert "for command_name in az helm jq kubectl kubelogin terraform timeout" in workflow
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
    assert '"field\\t\\($address)\\t\\($path | map(tostring) | join("."))"' in workflow
    assert '"replace-path\\t\\($address)\\t\\(map(tostring) | join("."))"' in workflow
    assert "(.change.replace_paths // [])[]?" in workflow
    assert '"before_value"' not in workflow
    assert '"after_value"' not in workflow
    assert 'environment_file="$output_dir/enforce.env"' in workflow
    assert 'environment_file="$(bash' not in workflow
    assert 'CONFIRM_DESTROY" != "destroy-sre-demo-lab"' in workflow
    assert "terraform apply -input=false -auto-approve" not in workflow
    assert workflow.count("terraform apply -json -input=false -auto-approve") == 3
    assert workflow.count("terraform apply -json -input=false -auto-approve -parallelism=2") == 1
    assert workflow.count('"$RUNNER_TEMP/sre-demo-lab.tfplan"') >= 3
    assert "terraform destroy" not in workflow
    assert "plan_args=(-destroy -refresh=false)" in workflow
    assert "Quiesce private DNS links before destroy" in workflow
    assert 'select(.type? == "azurerm_private_dns_zone_virtual_network_link")' in workflow
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
    assert "(.runs | length) == 10" in workflow
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


def test_scenario_lab_plan_diagnostic_projects_only_allowlisted_tokens(tmp_path: Path) -> None:
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
        "Error: retrieving private deployment value: "
        'Code="RequestDisallowedByPolicy" Message="private resource name"\n\n'
        "  with module.private.azurerm_private_endpoint.azure_openai,\n"
        '  on data-services.tf line 128, in resource "azurerm_private_endpoint" "azure_openai":\n',
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
    assert "provider_read" in result.stdout
    assert "request_disallowed_by_policy" in result.stdout
    assert "module.private.azurerm_private_endpoint.azure_openai" in result.stdout
    assert "RequestDisallowedByPolicy" in result.stdout
    assert "private deployment value" not in result.stdout
    assert "private resource name" not in result.stdout


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
    latency_runner = (REPO_ROOT / "scripts" / "catalog" / "measure-detection-latency.py").read_text(
        encoding="utf-8"
    )
    sweep = SWEEP_SCRIPT.read_text(encoding="utf-8")

    assert 'APPROVAL_REF = _env("FDAI_ENFORCE_APPROVAL_REF")' in runner
    assert 'd["approval_ref"] = APPROVAL_REF' in runner
    for source in (runner, latency_runner):
        assert 'BACKEND_CONTAINER = _env("FDAI_ENFORCE_BACKEND_CONTAINER")' in source
        assert 'BACKEND_IMAGE = _env("FDAI_ENFORCE_BACKEND_IMAGE")' in source
        assert "container=BACKEND_CONTAINER" in source
        assert 'bad_image=f"{BACKEND_IMAGE}:does-not-exist-' in source
    assert 'export FDAI_ENFORCE_APPROVAL_REF="$approval_ref"' in sweep
    assert 'SCENARIO_LAB_CONFIRM_ENFORCE:-}" != "true"' in sweep
    assert 'os.environ.get("FDAI_ENFORCE_REPORT_ROOT")' in runner
    assert "must be an absolute non-root path" in runner
    prepare = PREPARE_SCRIPT.read_text(encoding="utf-8")
    assert "helm show chart chaos-mesh/chaos-mesh" in prepare
    assert "az helm jq kubectl kubelogin python3 terraform" in prepare
    assert "--public-fqdn" in prepare
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
