from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _ROOT / ".github/workflows/deploy-dev.yml"
_WORKFLOW = _WORKFLOW_PATH.read_text(encoding="utf-8")
_CONVERGENCE = (_ROOT / "scripts/deployment/azure/verify_deploy_convergence.sh").read_text(
    encoding="utf-8"
)


def _step_names() -> tuple[str, ...]:
    return tuple(re.findall(r"^      - name: (.+)$", _WORKFLOW, re.MULTILINE))


def test_deploy_workflow_stays_within_reviewable_budget() -> None:
    assert len(_WORKFLOW.splitlines()) <= 2_320
    assert len(_step_names()) <= 56
    assert _WORKFLOW.count("        run: |") <= 47
    assert len(_step_names()) == len(set(_step_names()))


def test_deploy_workflow_uses_consolidated_boundaries() -> None:
    assert "Install pinned GitHub CLI for model verification" not in _WORKFLOW
    assert "Install pinned GitHub CLI for image verification" not in _WORKFLOW
    assert _WORKFLOW.count("Install pinned GitHub CLI") == 1
    assert _WORKFLOW.count("Validate deployment request") == 1
    assert "Validate runtime image request" not in _WORKFLOW
    assert "Validate design-mocks-only request" not in _WORKFLOW
    assert "Validate model-binding-only request" not in _WORKFLOW
    assert "Validate remote plan request" not in _WORKFLOW
    assert "Validate exact apply request" not in _WORKFLOW
    assert _WORKFLOW.count("Enforce bounded Terraform plan scope") == 1
    assert "Enforce design-mocks-only Terraform plan" not in _WORKFLOW
    assert "Enforce monitoring-only Terraform plan" not in _WORKFLOW
    assert "Enforce model-binding-only Terraform plan" not in _WORKFLOW


def test_deploy_workflow_isolates_cost_governance_plan_changes() -> None:
    target_step = _WORKFLOW.split("- name: Bind model-binding Terraform target", maxsplit=1)[
        1
    ].split("- name: Verify production architecture-review evidence", maxsplit=1)[0]

    assert "env.RUNTIME_IMAGE_PROFILE == 'cost-governance'" in target_step
    for address in (
        "azurerm_role_assignment.inventory_cost_reader",
        "module.compute.azurerm_container_app_job.cost_governance_collector[0]",
        "module.compute.azurerm_container_app_job.cost_governance_analyzer[0]",
    ):
        assert f"-target={address}" in target_step

    scope_step = _WORKFLOW.split("- name: Enforce bounded Terraform plan scope", maxsplit=1)[
        1
    ].split("- name: Reject destructive protected plan", maxsplit=1)[0]
    assert "env.RUNTIME_IMAGE_PROFILE == 'cost-governance'" in scope_step
    assert "mode=cost-governance" in scope_step


def test_pinned_github_cli_precedes_model_and_runtime_image_checks() -> None:
    installer = _WORKFLOW.index("- name: Install pinned GitHub CLI")
    installer_block = _WORKFLOW[installer:].split("      - name:", maxsplit=1)[0]

    assert "MODEL_BINDING_ONLY == 'true'" in installer_block
    assert "inputs.runtime_image_revision != ''" in installer_block
    assert installer < _WORKFLOW.index("- name: Verify model binding policy active digest")
    assert installer < _WORKFLOW.index("- name: Reverify active Core model fence")
    assert installer < _WORKFLOW.index("- name: Bind exact Core runtime image")


def test_deploy_workflow_skips_plan_only_work_during_apply() -> None:
    for step in (
        "Verify protected storage containers",
        "Adopt existing Azure resources",
        "Terraform format check",
        "Terraform validate",
    ):
        block = _WORKFLOW.split(f"- name: {step}", maxsplit=1)[1].split(
            "      - name:", maxsplit=1
        )[0]
        assert "!inputs.apply" in block


def test_resume_does_not_repeat_mutating_verification() -> None:
    for step in (
        "Run schema migrations",
        "Reconcile Foundry web-search agent",
        "Verify independent Executor effect and rollback",
        "Publish Executor authority effect receipt",
    ):
        block = _WORKFLOW.split(f"- name: {step}", maxsplit=1)[1].split(
            "      - name:", maxsplit=1
        )[0]
        assert "!inputs.resume_verification" in block


def test_deploy_workflow_invokes_reviewed_helpers() -> None:
    helpers = (
        "install-pinned-github-cli.sh",
        "validate_deploy_request.py",
        "bind-production-terraform-inputs.sh",
        "bind_core_runtime_image.sh",
        "verify_deploy_convergence.sh",
        "publish-console.sh",
        "build_dev_gateway_artifact.py",
        "run_runner_preflight.py",
        "enforce_plan_scope.py",
        "bootstrap-service-migrations.sh",
    )
    for helper in helpers:
        assert f"scripts/deployment/azure/{helper}" in _WORKFLOW
        assert (_ROOT / "scripts/deployment/azure" / helper).is_file()
    assert "verify_job_image.py" in _CONVERGENCE
    assert (_ROOT / "scripts/deployment/azure/verify_job_image.py").is_file()


def test_production_input_helper_preserves_hardening_contract() -> None:
    helper = (_ROOT / "scripts/deployment/azure/bind-production-terraform-inputs.sh").read_text(
        encoding="utf-8"
    )

    assert "@sha256:[0-9a-f]{64}" in helper
    assert "PROD_BUDGET_ALERT_EMAILS_JSON" in helper
    for value in (
        "TF_VAR_enable_resource_locks=true",
        "TF_VAR_kv_purge_protection_enabled=true",
        "TF_VAR_postgres_geo_redundant_backup=true",
        "TF_VAR_postgres_high_availability_mode=ZoneRedundant",
        "TF_VAR_acr_sku=Premium",
        "TF_VAR_enable_monitoring=true",
    ):
        assert value in helper


def test_deploy_workflow_initializes_remote_state_before_terraform_use() -> None:
    init = _WORKFLOW.index("- name: Initialize Terraform remote state")
    first_state_use = _WORKFLOW.index("- name: Verify model binding policy active digest")
    block = _WORKFLOW[init:first_state_use]

    assert "cp backend.azurerm.tf.example backend.tf" in block
    assert "terraform init -input=false" in block
    assert "resource_group_name=${{ vars.OPS_RESOURCE_GROUP_NAME }}" in block
    assert "storage_account_name=${{ vars.STATE_STORAGE_ACCOUNT }}" in block
    assert "key=fdai-${{ inputs.environment }}.tfstate" in block
    assert init < first_state_use


def test_core_image_provenance_verification_precedes_terraform_and_acr() -> None:
    request = _WORKFLOW.index("- name: Validate deployment request")
    init = _WORKFLOW.index("- name: Initialize Terraform remote state")
    bind = _WORKFLOW.index("- name: Bind exact Core runtime image")
    request_block = _WORKFLOW[request:].split("      - name:", maxsplit=1)[0]
    bind_block = _WORKFLOW[bind:].split("      - name:", maxsplit=1)[0]

    assert request < init < bind
    assert "bind_core_runtime_image.sh --verify-only" in request_block
    assert "bind_core_runtime_image.sh --bind-verified infra" in bind_block


def test_plan_only_verifies_storage_without_mutating_it() -> None:
    step = _WORKFLOW.index("- name: Verify protected storage containers")
    following = _WORKFLOW.index("- name: Initialize Terraform remote state")
    block = _WORKFLOW[step:following]

    assert "az storage container exists" in block
    assert '--subscription "$ARM_SUBSCRIPTION_ID"' in block
    assert "az storage container create" not in block
    assert "az storage blob upload" not in block


def test_plan_adopts_existing_operational_history_runner_role() -> None:
    start = _WORKFLOW.index("- name: Adopt existing Azure resources")
    end = _WORKFLOW.index("- name: Terraform format check")
    block = _WORKFLOW[start:end]

    assert 'local principal="$3"' in block
    assert "<<< 'try(module.operational_history_storage[0].id, \"\")'" in block
    assert (
        "module.operational_history_storage[0].azurerm_role_assignment."
        "terraform_runner_data_owner[0]"
    ) in block
    assert (
        'role_assignment_id "$operational_history_scope" '
        "'Storage Blob Data Owner' \"$DEPLOY_RUNNER_PRINCIPAL_ID\""
    ) in block


def test_gateway_publish_uses_bounded_cli_one_deploy() -> None:
    publish = _WORKFLOW.index("- name: Publish exact development operations gateway source")
    verify = _WORKFLOW.index("- name: Verify exact development operations gateway source")
    block = _WORKFLOW[publish:verify]

    assert "functions-action" not in _WORKFLOW
    assert "az functionapp deployment source config-zip" in block
    assert '--ids "$GATEWAY_FUNCTION_RESOURCE_ID"' in block
    assert "--src fdai-dev-operations-gateway.zip" in block
    assert "--build-remote true" in block
    assert "--timeout 900" in block


def test_registry_credentials_are_private_file_backed_and_cleaned() -> None:
    binder = (_ROOT / "scripts/deployment/azure/bind_core_runtime_image.sh").read_text(
        encoding="utf-8"
    )
    assert "--password " not in binder
    assert "--password=" not in binder
    assert "--password-stdin" not in binder
    assert "docker login" not in binder
    assert 'DOCKER_CONFIG="$docker_config" timeout 60s gh attestation verify' in binder
    assert 'rm -rf -- "$docker_config"' in binder
    assert '-H "Authorization: Bearer $registry_token"' not in binder
    assert '--header "@$bearer_header_file"' in binder
    assert 'chmod 0600 "$netrc_file" "$docker_config/config.json"' in binder
    assert 'json.dump({"auths": {"ghcr.io": {"auth": encoded}}}' in binder
    assert 'rm -rf -- "$private_dir"' in binder
    assert "gh api" not in binder
    assert "api.github.com" not in binder


def test_post_apply_verifies_inventory_job_image() -> None:
    assert "verify_job_image.py" in _CONVERGENCE
    assert '--expected-image "$TF_VAR_core_image"' in _CONVERGENCE
    assert 'job_name="ca-fdai-${TF_VAR_env}-${TF_VAR_region_short}-core-inventory"' in _CONVERGENCE
    assert 'resource_group="$(terraform output -raw resource_group_name)"' in _CONVERGENCE
    assert 'elif [[ "$OPERATIONAL_HISTORY_ONLY" != "true" ]]; then' in _CONVERGENCE


def test_operational_history_apply_ignores_unrelated_inventory_image_drift() -> None:
    guard = _CONVERGENCE.index('elif [[ "$OPERATIONAL_HISTORY_ONLY" != "true" ]]; then')
    inventory_readback = _CONVERGENCE.index('job_name="ca-fdai-', guard)
    guard_end = _CONVERGENCE.index("\nelse", inventory_readback)

    assert guard < inventory_readback < guard_end
