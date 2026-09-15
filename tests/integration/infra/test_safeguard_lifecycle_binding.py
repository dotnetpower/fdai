"""Terraform source-revision binding for production safeguard evidence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "infra" / "services" / "core-control-plane"


def test_core_service_binds_exact_source_revision_to_runtime() -> None:
    platform_outputs = (ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
    root_variables = (SERVICE_ROOT / "variables.tf").read_text(encoding="utf-8")
    root_module = (SERVICE_ROOT / "main.tf").read_text(encoding="utf-8")
    module_variables = (SERVICE_ROOT / "modules/core-control-plane/variables.tf").read_text(
        encoding="utf-8"
    )
    module = (SERVICE_ROOT / "modules/core-control-plane/main.tf").read_text(encoding="utf-8")

    assert 'variable "source_revision"' in root_variables
    assert "source_revision            = var.source_revision" in root_module
    assert 'variable "source_revision"' in module_variables
    assert '{ name = "FDAI_SOURCE_REVISION", value = var.source_revision }' in module
    assert (
        '{ name = "FDAI_OHL_SOURCE_MI_CLIENT_ID", '
        "value = var.observation_context.source_identity_client_id }"
    ) in module
    assert (
        '{ name = "FDAI_OHL_VM_START_EXECUTOR_CREDENTIAL_LINEAGE", '
        "value = var.observation_context.vm_start_executor_credential_lineage }"
    ) in module
    observation_binding = platform_outputs.split(
        'output "ohl_observation_context_binding"', maxsplit=1
    )[1].split('output "stewardship_gitops_binding"', maxsplit=1)[0]
    assert "source_identity_resource_id = module.inventory_identity.resource_id" in (
        observation_binding
    )
    assert "module.identity_finops.client_id" in observation_binding
    assert "module.identity_resilience.client_id" in observation_binding


def test_deploy_workflow_forwards_source_revision_to_tfvars() -> None:
    workflow = (ROOT / ".github/workflows/service-deploy.yml").read_text(encoding="utf-8")

    assert 'echo "SOURCE_REVISION=$SOURCE_REVISION" >> "$GITHUB_ENV"' in workflow
    assert 'if [[ "$SERVICE" == "core-control-plane" ]]; then' in workflow
    assert 'SOURCE_REVISION="$source_revision_binding" \\' in workflow


def test_core_service_always_binds_the_recovery_observer_identity() -> None:
    module = (SERVICE_ROOT / "modules/core-control-plane/main.tf").read_text(encoding="utf-8")
    observer_binding = (
        '{ name = "FDAI_WORKFLOW_RECOVERY_OBSERVER_IDENTITIES", '
        'value = "observer:heimdall:azure-container-apps" }'
    )

    assert module.count(observer_binding) == 1
    assert module.index(observer_binding) < module.index(
        'var.teams_approval_destination.team_id == ""'
    )
