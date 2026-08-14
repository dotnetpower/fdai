from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "compute" / "container-apps"


def test_browser_evidence_cleanup_job_is_opt_in_and_bounded() -> None:
    root_variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    module_variables = (_MODULE / "variables.tf").read_text(encoding="utf-8")
    job = (_MODULE / "browser_evidence_cleanup_job.tf").read_text(encoding="utf-8")

    assert 'default     = ""' in _variable_block(
        root_variables, "browser_evidence_cleanup_cron_expression"
    )
    assert 'default     = ""' in _variable_block(
        module_variables, "browser_evidence_cleanup_cron_expression"
    )
    assert 'count = var.browser_evidence_cleanup_cron_expression == "" ? 0 : 1' in job
    assert "replica_retry_limit          = 0" in job
    assert "parallelism              = 1" in job
    assert "var.browser_evidence_cleanup_limit >= 1" in root_variables
    assert "var.browser_evidence_cleanup_limit <= 500" in root_variables


def test_browser_evidence_cleanup_job_has_no_executor_identity() -> None:
    job = (_MODULE / "browser_evidence_cleanup_job.tf").read_text(encoding="utf-8")

    assert "inventory_identity_id" in job
    assert "executor_identity" not in job
    assert "state_store_dsn_secret_id" in job
    assert '"fdai:component" = "browser-gc"' in job
    assert 'name        = "FDAI_DATABASE_URL"' in job
    assert 'name  = "FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT"' in job
    assert 'command = ["python", "-m", "fdai.delivery.browser_evidence_cleanup_cli"]' in job


def test_browser_evidence_cleanup_job_is_wired_through_root_and_outputs() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    module_outputs = (_MODULE / "outputs.tf").read_text(encoding="utf-8")
    root_outputs = (_ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")

    assert '"caj-${var.workload}${local.full_suffix}-browser-gc"' in root
    assert len("caj-fdai-staging-krc-browser-gc") <= 32
    assert "browser_evidence_cleanup_cron_expression  =" in root
    assert "browser_evidence_cleanup_limit            =" in root
    assert 'output "browser_evidence_cleanup_job_id"' in module_outputs
    assert 'output "browser_evidence_cleanup_job_id"' in root_outputs


def test_browser_evidence_cleanup_job_is_exposed_in_environment_examples() -> None:
    for name in ("dev.tfvars.example", "staging.tfvars.example", "prod.tfvars.example"):
        example = (_ROOT / "infra" / "envs" / name).read_text(encoding="utf-8")
        assert "browser_evidence_cleanup_cron_expression" in example
        assert "browser_evidence_cleanup_limit           = 100 # default" in example


def _variable_block(source: str, name: str) -> str:
    start = source.index(f'variable "{name}"')
    end = source.index("\n}\n", start) + 3
    return source[start:end]
