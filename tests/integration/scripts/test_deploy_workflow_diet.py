from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _ROOT / ".github/workflows/deploy-dev.yml"
_WORKFLOW = _WORKFLOW_PATH.read_text(encoding="utf-8")


def _step_names() -> tuple[str, ...]:
    return tuple(re.findall(r"^      - name: (.+)$", _WORKFLOW, re.MULTILINE))


def test_deploy_workflow_stays_within_reviewable_budget() -> None:
    assert len(_WORKFLOW.splitlines()) <= 2_300
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


def test_pinned_github_cli_precedes_model_attestation_checks() -> None:
    installer = _WORKFLOW.index("- name: Install pinned GitHub CLI")
    installer_block = _WORKFLOW[installer:].split("      - name:", maxsplit=1)[0]

    assert "MODEL_BINDING_ONLY == 'true'" in installer_block
    assert installer < _WORKFLOW.index("- name: Verify model binding policy active digest")
    assert installer < _WORKFLOW.index("- name: Reverify active Core model fence")


def test_deploy_workflow_skips_plan_only_work_during_apply() -> None:
    for step in (
        "Ensure protected storage containers",
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
        "bind_isolated_executor_image.sh",
        "build_dev_gateway_artifact.py",
        "run_runner_preflight.py",
        "enforce_plan_scope.py",
        "bootstrap-service-migrations.sh",
    )
    for helper in helpers:
        assert f"scripts/deployment/azure/{helper}" in _WORKFLOW
        assert (_ROOT / "scripts/deployment/azure" / helper).is_file()


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


def test_registry_credentials_are_not_process_arguments() -> None:
    binder = (_ROOT / "scripts/deployment/azure/bind_isolated_executor_image.sh").read_text(
        encoding="utf-8"
    )
    assert "--password" not in binder
    assert "--user" not in binder
    assert 'echo "::add-mask::$registry_token"' in binder
