from __future__ import annotations

from pathlib import Path

from fdai_cost_governance.job_cli import _cost_retry_after_seconds

_ROOT = Path(__file__).resolve().parents[3]


def test_cost_retry_after_uses_longest_provider_delay_case_insensitively() -> None:
    delay = _cost_retry_after_seconds(
        {
            "Retry-After": "2",
            "X-MS-RATELIMIT-MICROSOFT.COSTMANAGEMENT-ENTITY-RETRY-AFTER": "7",
            "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after": "5",
        }
    )

    assert delay == 7


def test_package_declares_both_job_entrypoints() -> None:
    pyproject = (_ROOT / "extensions/cost-governance/pyproject.toml").read_text(encoding="utf-8")
    assert 'fdai-cost-collector = "fdai_cost_governance.job_cli:collector_main"' in pyproject
    assert 'fdai-cost-analyzer = "fdai_cost_governance.job_cli:analyzer_main"' in pyproject
    assert 'fdai-cost-lifecycle = "fdai_cost_governance.lifecycle_cli:main"' in pyproject
    assert 'fdai-cost-validation = "fdai_cost_governance.validation_cli:main"' in pyproject


def test_optional_jobs_are_serial_and_use_non_executor_collection_identity() -> None:
    terraform = (_ROOT / "infra/cost_governance_jobs.tf").read_text(encoding="utf-8")
    legacy_path = _ROOT / "infra/modules/compute/container-apps/cost_governance_jobs.tf"

    assert not legacy_path.exists()
    assert terraform.count("parallelism              = 1") == 2
    assert (
        terraform.count(
            "identity_ids = [data.azurerm_user_assigned_identity.cost_governance_inventory[0].id]"
        )
        == 2
    )
    assert "var.finops_identity" not in terraform
    assert "fdai-cost-collector" in terraform
    assert "fdai-cost-analyzer" in terraform
    assert "FDAI_COST_COLLECTION_MI_CLIENT_ID" in terraform
    assert 'data "azurerm_container_app_environment" "cost_governance"' in terraform
    assert 'data "azurerm_user_assigned_identity" "cost_governance_inventory"' in terraform
    assert (
        "from = module.compute.azurerm_container_app_job.cost_governance_collector[0]" in terraform
    )
    assert (
        "from = module.compute.azurerm_container_app_job.cost_governance_analyzer[0]" in terraform
    )
    for unrelated_dependency in (
        "module.compute.environment_id",
        "module.network",
        "module.scheduler_identity",
        "module.state_store",
    ):
        assert unrelated_dependency not in terraform


def test_job_schedules_default_absent() -> None:
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    for name in (
        "cost_governance_collector_cron_expression",
        "cost_governance_analyzer_cron_expression",
    ):
        declaration = variables.split(f'variable "{name}"', 1)[1].split("}", 1)[0]
        assert 'default     = ""' in declaration


def test_cost_governance_image_is_digest_pinned_and_job_names_are_exported() -> None:
    root_variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    root_outputs = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")

    declaration = root_variables.split('variable "cost_governance_image"', 1)[1].split("\n}\n", 1)[
        0
    ]
    assert "@sha256:[0-9a-f]{64}" in declaration
    for name in (
        "cost_governance_collector_job_name",
        "cost_governance_analyzer_job_name",
    ):
        assert f'output "{name}"' in root_outputs
