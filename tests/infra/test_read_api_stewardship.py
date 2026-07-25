from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_read_api_requires_real_complete_stewardship_bindings() -> None:
    module = (_ROOT / "infra" / "modules" / "read-api" / "container-app" / "main.tf").read_text(
        encoding="utf-8"
    )

    assert 'trimspace(var.stewardship_maintainers) != ""' in module
    assert 'var.iam_directory_provider == "entra"' in module
    for agent in (
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Vidar",
        "Var",
        "Bragi",
        "Saga",
        "Mimir",
        "Muninn",
        "Norns",
        "Njord",
        "Freyr",
    ):
        assert f'"{agent}"' in module
    assert "read API requires stewardship bindings" in module


def test_inventory_job_inherits_required_runtime_config() -> None:
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert "for_each = local.core_config_env" in job
    assert 'command = ["python", "-m", "fdai.delivery.inventory_sync_cli"]' in job
