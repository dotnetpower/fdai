from __future__ import annotations

import importlib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "measurement-runners"


def test_measurement_runner_entrypoint_is_importable() -> None:
    module = importlib.import_module("fdai.delivery.measurement_runner_cli")

    assert module.MeasurementMode.BASELINE.value == "baseline"
    assert module.MeasurementMode.GROWTH.value == "growth"
    assert module.MeasurementMode.OPERATIONAL_PROMOTION.value == "operational-promotion"


def test_measurement_jobs_use_a_dedicated_non_executor_identity() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    jobs = (_MODULE / "measurement_runners.tf").read_text(encoding="utf-8")
    openai = (_ROOT / "infra" / "modules" / "llm" / "azure-openai" / "main.tf").read_text(
        encoding="utf-8"
    )

    assert 'name                = "id-${var.workload}${local.full_suffix}-measurement"' in root
    assert (
        "measurement_identity_id             = module.measurement_identity[0].resource_id" in root
    )
    assert "FDAI_MI_CLIENT_ID                 = module.measurement_identity[0].client_id" in root
    assert "executor_identity_id" not in jobs
    assert "var.measurement_identity_id" in jobs
    assert "measurement_kv_secrets_user" in root
    assert "measurement_acr_pull" in root
    measurement_role_blocks = [
        block
        for block in re.findall(
            r'resource "azurerm_role_assignment" "[^"]+" \{.*?^\}',
            root,
            flags=re.MULTILINE | re.DOTALL,
        )
        if "module.measurement_identity[0].principal_id" in block
    ]
    assert len(measurement_role_blocks) == 2
    assert all(
        role in "\n".join(measurement_role_blocks)
        for role in ('"AcrPull"', '"Key Vault Secrets User"')
    )
    assert "Contributor" not in "\n".join(measurement_role_blocks)
    assert 'role_definition_name = "Cognitive Services OpenAI User"' in openai


def test_root_composition_preserves_opt_in_inputs_and_nullable_outputs() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    outputs = (_ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")

    for name in (
        "baseline_measurement_enabled",
        "pattern_growth_measurement_enabled",
        "operational_promotion_measurement_enabled",
    ):
        assert "default     = false" in _variable_block(variables, name)
    assert "!var.pattern_growth_measurement_enabled || var.enable_llm" in _variable_block(
        variables, "pattern_growth_measurement_enabled"
    )
    assert "count  = local.measurement_runners_enabled ? 1 : 0" in root
    assert "baseline_enabled                    = var.baseline_measurement_enabled" in root
    assert "growth_enabled                      = var.pattern_growth_measurement_enabled" in root
    assert "try(module.measurement_runners[0].baseline_job_name, null)" in outputs
    assert "try(module.measurement_runners[0].growth_job_name, null)" in outputs
    assert "try(module.measurement_runners[0].operational_promotion_job_name, null)" in outputs


def _variable_block(source: str, name: str) -> str:
    start = source.index(f'variable "{name}"')
    end = source.index("\n}\n", start) + 3
    return source[start:end]
