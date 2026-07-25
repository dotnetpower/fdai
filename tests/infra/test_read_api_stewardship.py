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
