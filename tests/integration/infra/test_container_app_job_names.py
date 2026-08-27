"""Container Apps Job naming contracts across deployment environments."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra/modules/compute/container-apps"
_SUFFIXES = {
    "analyzer": "analyzer",
    "canary": "canary",
    "forecast": "forecast",
    "inventory": "inventory",
    "observation": "observation",
    "ohl_evidence": "ohl-evidence",
    "scheduler": "scheduler",
}


def _names(environment: str) -> dict[str, str]:
    full_suffix = "" if not environment else f"-{environment}-krc"
    app_name = f"ca-fdai{full_suffix}-core"
    env_suffix = "" if not environment else f"-{environment}"
    compact_prefix = f"caj-fdai{env_suffix}"
    return {
        key: (
            f"{app_name}-{suffix}"
            if len(f"{app_name}-{suffix}") <= 32
            else f"{compact_prefix}-{suffix}"
        )
        for key, suffix in _SUFFIXES.items()
    }


def _provider_schema_name(environment: str) -> str:
    full_suffix = "" if not environment else f"-{environment}-krc"
    env_suffix = "" if not environment else f"-{environment}"
    preferred = f"caj-fdai{full_suffix}-provider-schema"
    return preferred if len(preferred) <= 32 else f"caj-fdai{env_suffix}-provider"


def test_every_environment_emits_bounded_job_names() -> None:
    for environment in ("", "dev", "staging", "prod"):
        names = _names(environment)
        assert all(len(name) <= 32 for name in names.values())
        assert len(_provider_schema_name(environment)) <= 32

    assert _names("dev")["inventory"] == "ca-fdai-dev-krc-core-inventory"
    assert _names("staging")["inventory"] == "caj-fdai-staging-inventory"
    assert _names("prod")["observation"] == "caj-fdai-prod-observation"
    assert _provider_schema_name("dev") == "caj-fdai-dev-krc-provider-schema"
    assert _provider_schema_name("staging") == "caj-fdai-staging-provider"


def test_terraform_resources_use_the_shared_bounded_name_map() -> None:
    for key, filename in (
        ("analyzer", "analyzer_tick_job.tf"),
        ("canary", "canary_job.tf"),
        ("forecast", "forecast_tick_job.tf"),
        ("inventory", "inventory_job.tf"),
        ("observation", "observation_campaign_job.tf"),
        ("ohl_evidence", "ohl_evidence_job.tf"),
        ("scheduler", "scheduler_job.tf"),
    ):
        source = (_MODULE / filename).read_text(encoding="utf-8")
        assert f"name                         = local.core_job_names.{key}" in source

    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
    assert 'core_job_name_prefix         = "caj-${var.workload}${local.env_suffix}"' in root
    assert 'length("caj-${var.workload}${local.full_suffix}-provider-schema") <= 32' in root
