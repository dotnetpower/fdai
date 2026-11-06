"""Regression coverage for CI change-scope routing and Lifecycle Hub UI/Python gates."""

from __future__ import annotations

from pathlib import Path

import yaml
from scripts.quality.ci.resolve_test_scope import ChangeScope, classify_paths

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_lifecycle_hub_ui_paths_trigger_operator_and_python_scopes() -> None:
    for path in ("lifecycle/hub/ui/src/app.tsx", "lifecycle/release-hub/ui/src/app.tsx"):
        scope = classify_paths([path])

        assert scope == ChangeScope(
            python=True,
            docs=True,
            terraform=False,
            operator=True,
            evaluation=False,
            dependencies=False,
            scenarios=False,
        )
        assert scope.operator is True
        assert scope.python is True


def test_operator_surfaces_and_ci_wire_lifecycle_hub_ui_and_lifecycle_ruff_gates() -> None:
    runner = (_REPO_ROOT / "scripts/quality/ci/run-operator-surfaces.sh").read_text(
        encoding="utf-8"
    )
    for command in (
        "npm --prefix lifecycle/hub/ui run typecheck",
        "npm --prefix lifecycle/hub/ui test",
        "npm --prefix lifecycle/hub/ui run build",
        "npm --prefix lifecycle/release-hub/ui run typecheck",
        "npm --prefix lifecycle/release-hub/ui test",
        "npm --prefix lifecycle/release-hub/ui run build",
    ):
        assert command in runner

    workflow = yaml.safe_load((_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    operator_steps = {step["name"]: step for step in workflow["jobs"]["operator-surfaces"]["steps"]}
    cache_paths = [
        line.strip()
        for line in operator_steps["Set up Node.js"]["with"]["cache-dependency-path"].splitlines()
    ]
    assert "lifecycle/hub/ui/package-lock.json" in cache_paths
    assert "lifecycle/release-hub/ui/package-lock.json" in cache_paths
    assert (
        operator_steps["Install locked Lifecycle Hub UI dependencies"]["run"]
        == "npm --prefix lifecycle/hub/ui ci --no-audit --no-fund"
    )
    assert (
        operator_steps["Install locked Release Hub UI dependencies"]["run"]
        == "npm --prefix lifecycle/release-hub/ui ci --no-audit --no-fund"
    )

    terraform_steps = {
        step["name"]: step for step in workflow["jobs"]["terraform-validate"]["steps"]
    }
    hub_tf_run = terraform_steps["terraform validate and test (Hub roots, mocked providers)"]["run"]
    assert "for hub_root in release-hub lifecycle-hub; do" in hub_tf_run
    assert 'terraform -chdir="$hub_root" validate' in hub_tf_run
    assert 'terraform -chdir="$hub_root" test' in hub_tf_run

    contracts_steps = {step["name"]: step for step in workflow["jobs"]["contracts"]["steps"]}
    lint_run = contracts_steps["Run Python lint and static contracts"]["run"]
    assert (
        "uv run ruff format --check services packages tests extensions/code-assurance lifecycle"
        in lint_run
    )
    assert (
        "uv run ruff check services packages tests extensions/code-assurance lifecycle" in lint_run
    )
