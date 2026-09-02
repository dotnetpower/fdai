"""Terraform contracts for Operator API Azure resource names."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_MAIN = REPO_ROOT / "infra" / "main.tf"
SERVICE_VARIABLES = REPO_ROOT / "infra" / "services" / "operator-service" / "variables.tf"


def test_operator_api_physical_names_use_current_component() -> None:
    root = " ".join(ROOT_MAIN.read_text(encoding="utf-8").split())

    identity_name = 'name = "id-${var.workload}${local.full_suffix}-operator-api"'
    container_app_name = 'name = "ca-${var.workload}${local.full_suffix}-operator-api"'
    assert identity_name in root
    assert container_app_name in root
    assert 'name = "id-${var.workload}${local.full_suffix}-readapi"' not in root
    assert 'name = "ca-${var.workload}${local.full_suffix}-readapi"' not in root


def test_independent_operator_service_bounds_legacy_physical_name_compatibility() -> None:
    variables = SERVICE_VARIABLES.read_text(encoding="utf-8")

    assert 'condition     = can(regex("-(operator-api|readapi)$", var.name))' in variables
    assert (
        'error_message = "Operator service Container App name must end with -operator-api or '
        'the legacy -readapi compatibility suffix."' in variables
    )
