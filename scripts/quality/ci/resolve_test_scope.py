"""Classify a Git diff for expensive CI test jobs."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[3]
_PYTHON_PREFIXES = (
    ".github/actions/setup-opa/",
    "eval/",
    "packages/",
    "services/",
    "src/",
    "tests/",
    "scripts/",
    "alembic/",
    "config/",
    "examples/",
    "extensions/",
    "mocks/",
    "policies/",
    "rule-catalog/",
    "tools/",
)
_PYTHON_FILES = frozenset(
    {
        "alembic.ini",
        "Dockerfile",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/ci.yml",
    }
)
_TERRAFORM_PREFIXES = ("infra/",)
_TERRAFORM_FILES = frozenset(
    {
        ".github/workflows/ci.yml",
    }
)
_DOC_PREFIXES = ("docs/", "scripts/quality/localization/")
_DOC_FILES = frozenset(
    {
        "README.md",
        "README-ko.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "DEVELOPING.md",
        ".github/copilot-instructions.md",
        ".github/workflows/ci.yml",
        "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json",
    }
)
_GUIDANCE_PREFIXES = (
    ".github/instructions/",
    ".github/skills/",
    ".github/prompts/",
    ".github/agents/",
)
_OPERATOR_PREFIXES = (
    "console/",
    "cli/",
    "eval/",
    "ui/",
    "mocks/ui/",
    "packages/",
    "src/",
    "services/core-control-plane/src/fdai/shared/contracts/",
    "config/",
    "extensions/",
    "rule-catalog/vocabulary/",
    "services/operator-service/",
    "tools/architecture-diagrams/assets/",
)
_OPERATOR_FILES = _PYTHON_FILES | frozenset(
    {
        ".github/workflows/ci.yml",
        "scripts/quality/ci/run-operator-surfaces.sh",
    }
)
_EVALUATION_PREFIXES = (
    "eval/",
    "evaluation-sdk/",
    "benchmarks/sregym/",
    "benchmarks/cybergym/",
    "extensions/",
    "packages/",
    "src/",
)
_EVALUATION_FILES = _PYTHON_FILES | frozenset(
    {
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "uv.lock",
    }
)
_DEPENDENCY_FILES = frozenset(
    {
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "uv.lock",
    }
)
_SCENARIO_PREFIXES = ("services/core-control-plane/tests/scenarios/",)
_SCENARIO_FILES = frozenset(
    {
        ".github/workflows/ci.yml",
        "scripts/quality/ci/check-frozen-scenario-additions.py",
    }
)


class ChangeScope(NamedTuple):
    """Expensive CI surfaces affected by one immutable Git diff."""

    python: bool
    docs: bool
    terraform: bool
    operator: bool
    evaluation: bool
    dependencies: bool
    scenarios: bool


def _classify_path(path: str) -> ChangeScope:
    if path.endswith(".md") and path.startswith(_GUIDANCE_PREFIXES):
        return ChangeScope(False, True, False, False, False, False, False)
    python = path.startswith(_PYTHON_PREFIXES) or path in _PYTHON_FILES
    return ChangeScope(
        python=python,
        docs=python or path.startswith(_DOC_PREFIXES) or path in _DOC_FILES,
        terraform=path.startswith(_TERRAFORM_PREFIXES) or path in _TERRAFORM_FILES,
        operator=path.startswith(_OPERATOR_PREFIXES) or path in _OPERATOR_FILES,
        evaluation=path.startswith(_EVALUATION_PREFIXES) or path in _EVALUATION_FILES,
        dependencies=path in _DEPENDENCY_FILES,
        scenarios=path.startswith(_SCENARIO_PREFIXES) or path in _SCENARIO_FILES,
    )


def classify_paths(paths: list[str]) -> ChangeScope:
    path_scopes = [_classify_path(path) for path in paths]
    if any(not any(scope) for scope in path_scopes):
        return ChangeScope(
            python=True,
            docs=True,
            terraform=True,
            operator=True,
            evaluation=True,
            dependencies=True,
            scenarios=True,
        )
    return ChangeScope(
        python=any(scope.python for scope in path_scopes),
        docs=any(scope.docs for scope in path_scopes),
        terraform=any(scope.terraform for scope in path_scopes),
        operator=any(scope.operator for scope in path_scopes),
        evaluation=any(scope.evaluation for scope in path_scopes),
        dependencies=any(scope.dependencies for scope in path_scopes),
        scenarios=any(scope.scenarios for scope in path_scopes),
    )


def _changed_paths(diff_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", diff_range],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", required=True, dest="diff_range")
    args = parser.parse_args()
    scope = classify_paths(_changed_paths(args.diff_range))
    output = Path(os.environ["GITHUB_OUTPUT"])
    with output.open("a", encoding="utf-8") as stream:
        for name, enabled in scope._asdict().items():
            stream.write(f"{name}={str(enabled).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
