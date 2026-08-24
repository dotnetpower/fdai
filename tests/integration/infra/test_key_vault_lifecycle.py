from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_provider_roots_permanently_delete_recreatable_resources() -> None:
    shared = (_ROOT / "infra" / "versions.tf").read_text(encoding="utf-8")
    scenario_lab = (_ROOT / "infra" / "scenario-lab" / "versions.tf").read_text(encoding="utf-8")
    bootstrap = (_ROOT / "infra" / "bootstrap" / "versions.tf").read_text(encoding="utf-8")
    dev_access = (_ROOT / "tools" / "dev-access" / "infra" / "versions.tf").read_text(
        encoding="utf-8"
    )

    for provider_config in (shared, scenario_lab):
        assert "purge_soft_delete_on_destroy    = true" in provider_config
        assert "recover_soft_deleted_key_vaults = true" in provider_config
        assert "permanently_delete_on_destroy = true" in provider_config

    assert "cognitive_account" in shared
    assert "purge_soft_delete_on_destroy = true" in shared

    for provider_config in (shared, scenario_lab, bootstrap, dev_access):
        assert "prevent_deletion_if_contains_resources = false" in provider_config


def test_standard_environments_remain_immediately_recreatable() -> None:
    production_gate = (_ROOT / "infra" / "production-gates.tf").read_text(encoding="utf-8")
    production_values = (_ROOT / "infra" / "envs" / "prod.tfvars.example").read_text(
        encoding="utf-8"
    )
    staging_values = (_ROOT / "infra" / "envs" / "staging.tfvars.example").read_text(
        encoding="utf-8"
    )
    bootstrap_variables = (_ROOT / "infra" / "bootstrap" / "variables.tf").read_text(
        encoding="utf-8"
    )
    bootstrap_values = (_ROOT / "infra" / "bootstrap" / "bootstrap.tfvars.example").read_text(
        encoding="utf-8"
    )
    module_variables = (
        _ROOT / "infra" / "modules" / "secret-store" / "key-vault" / "variables.tf"
    ).read_text(encoding="utf-8")

    assert "!var.enable_resource_locks" in production_gate
    assert "!var.kv_purge_protection_enabled" in production_gate
    assert "var.kv_soft_delete_retention_days == 7" in production_gate
    assert "enable_resource_locks          = false" in production_values
    assert "kv_purge_protection_enabled    = false" in production_values
    assert "kv_soft_delete_retention_days  = 7" in production_values
    assert "enable_resource_locks          = false" in staging_values
    assert "enable_state_lock = false" in bootstrap_values
    assert 'variable "enable_state_lock"' in bootstrap_variables
    assert "default     = false" in bootstrap_variables
    assert 'variable "purge_protection_enabled"' in module_variables
    assert 'variable "soft_delete_retention_days"' in module_variables
    assert module_variables.count("default     = false") >= 1
    assert module_variables.count("default     = 7") >= 1
