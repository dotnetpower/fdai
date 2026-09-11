"""Terraform source-revision binding for production safeguard evidence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "infra" / "services" / "core-control-plane"


def test_core_service_binds_exact_source_revision_to_runtime() -> None:
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


def test_deploy_workflow_forwards_source_revision_to_tfvars() -> None:
    workflow = (ROOT / ".github/workflows/service-deploy.yml").read_text(encoding="utf-8")

    assert 'echo "SOURCE_REVISION=$SOURCE_REVISION" >> "$GITHUB_ENV"' in workflow
    assert 'if [[ "$SERVICE" == "core-control-plane" ]]; then' in workflow
    assert 'SOURCE_REVISION="$source_revision_binding" \\' in workflow
