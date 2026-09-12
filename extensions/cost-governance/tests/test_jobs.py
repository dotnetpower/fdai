from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_package_declares_both_job_entrypoints() -> None:
    pyproject = (_ROOT / "extensions/cost-governance/pyproject.toml").read_text(encoding="utf-8")
    assert 'fdai-cost-collector = "fdai_cost_governance.job_cli:collector_main"' in pyproject
    assert 'fdai-cost-analyzer = "fdai_cost_governance.job_cli:analyzer_main"' in pyproject
    assert 'fdai-cost-lifecycle = "fdai_cost_governance.lifecycle_cli:main"' in pyproject
    assert 'fdai-cost-validation = "fdai_cost_governance.validation_cli:main"' in pyproject


def test_optional_jobs_are_serial_and_use_non_executor_collection_identity() -> None:
    terraform = (_ROOT / "infra/modules/compute/container-apps/cost_governance_jobs.tf").read_text(
        encoding="utf-8"
    )
    assert terraform.count("parallelism              = 1") == 2
    assert terraform.count("identity_ids = [var.inventory_identity_id]") == 2
    assert "var.finops_identity" not in terraform
    assert "fdai-cost-collector" in terraform
    assert "fdai-cost-analyzer" in terraform
    assert "FDAI_COST_COLLECTION_MI_CLIENT_ID" in terraform


def test_job_schedules_default_absent() -> None:
    variables = (_ROOT / "infra/modules/compute/container-apps/variables.tf").read_text(
        encoding="utf-8"
    )
    for name in (
        "cost_governance_collector_cron_expression",
        "cost_governance_analyzer_cron_expression",
    ):
        declaration = variables.split(f'variable "{name}"', 1)[1].split("}", 1)[0]
        assert 'default     = ""' in declaration


def test_cost_governance_image_is_digest_pinned_and_job_names_are_exported() -> None:
    root_variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    module_variables = (_ROOT / "infra/modules/compute/container-apps/variables.tf").read_text(
        encoding="utf-8"
    )
    module_outputs = (_ROOT / "infra/modules/compute/container-apps/outputs.tf").read_text(
        encoding="utf-8"
    )
    root_outputs = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")

    for source in (root_variables, module_variables):
        declaration = source.split('variable "cost_governance_image"', 1)[1].split("\n}\n", 1)[0]
        assert "@sha256:[0-9a-f]{64}" in declaration
    for name in (
        "cost_governance_collector_job_name",
        "cost_governance_analyzer_job_name",
    ):
        assert f'output "{name}"' in module_outputs
        assert f'output "{name}"' in root_outputs
