"""Deterministic pytest shard assignment contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.quality.ci.pytest_shard import _assign_shards, _load_duration_weights
from scripts.quality.ci.resolve_test_scope import ChangeScope, classify_paths


def test_shard_assignment_is_stable_balanced_and_bounded() -> None:
    weights = {
        Path("tests/heavy.py"): 8,
        Path("tests/medium.py"): 5,
        Path("tests/light-a.py"): 3,
        Path("tests/light-b.py"): 2,
    }

    assignments = _assign_shards(weights, 3)

    assert assignments == _assign_shards(dict(reversed(tuple(weights.items()))), 3)
    assert set(assignments) == set(weights)
    assert set(assignments.values()) <= {0, 1, 2}
    loads = [
        sum(weight for path, weight in weights.items() if assignments[path] == shard)
        for shard in range(3)
    ]
    assert max(loads) - min(loads) <= max(weights.values())


@pytest.mark.parametrize(
    ("weights", "count", "message"),
    [
        ({Path("tests/test_one.py"): 1}, 0, "count must be >= 1"),
        (
            {Path("tests/test_one.py"): 0},
            1,
            "file weights must be positive finite numbers",
        ),
    ],
)
def test_shard_assignment_rejects_invalid_weights(
    weights: dict[Path, int],
    count: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _assign_shards(weights, count)


def test_duration_weights_are_versioned_and_validate_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "durations.json"
    manifest.write_text(
        """
{
  "schema_version": 1,
  "default_seconds_per_test": 0.01,
  "files": {
    "tests/test_fast.py": 0.5,
    "tests/test_slow.py": 12.25
  }
}
""".strip(),
        encoding="utf-8",
    )

    default, weights = _load_duration_weights(manifest)

    assert default == 0.01
    assert weights == {
        Path("tests/test_fast.py"): 0.5,
        Path("tests/test_slow.py"): 12.25,
    }

    manifest.write_text(
        '{"schema_version":1,"default_seconds_per_test":0.01,"files":{"../outside.py":1}}',
        encoding="utf-8",
    )
    with pytest.raises(pytest.UsageError, match="invalid pytest shard duration path"):
        _load_duration_weights(manifest)


def test_change_scope_classification_skips_expensive_python_for_docs_and_console() -> None:
    assert classify_paths(["docs/roadmap/architecture/project-structure.md"]) == ChangeScope(
        python=False,
        docs=True,
        terraform=False,
        operator=False,
        evaluation=False,
        dependencies=False,
        scenarios=False,
    )
    assert classify_paths(["console/src/app.tsx"]) == ChangeScope(
        python=False,
        docs=False,
        terraform=False,
        operator=True,
        evaluation=False,
        dependencies=False,
        scenarios=False,
    )
    assert classify_paths(["services/core-control-plane/src/fdai/core/risk_gate/gate.py"]).python
    assert classify_paths(["alembic/versions/revision.py"]).python
    assert classify_paths(["config/rbac-groups.yaml"]).python
    assert classify_paths(["tools/seed_p1_rules.py"]).python
    assert classify_paths(["extensions/code-assurance/assets/skill.json"]) == ChangeScope(
        python=True,
        docs=True,
        terraform=False,
        operator=True,
        evaluation=True,
        dependencies=False,
        scenarios=False,
    )
    assert classify_paths(["infra/scenario-lab/main.tf"]).terraform
    assert classify_paths(
        ["services/core-control-plane/tests/core/risk_gate/test_gate.py", "README.md"]
    ).python


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("scripts/quality/localization/check-translations.sh", "docs"),
        (
            "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json",
            "docs",
        ),
        (".github/instructions/architecture.instructions.md", "docs"),
        (".github/actions/setup-opa/action.yml", "python"),
        ("cli/src/main.ts", "operator"),
        ("ui/calm-slate-tokens.css", "operator"),
        ("mocks/ui/assets/calm-slate.css", "operator"),
        ("packages/network-topology-contracts/src/index.d.ts", "operator"),
        ("packages/service-contracts/openapi.json", "operator"),
        ("packages/github-app-auth/pyproject.toml", "operator"),
        ("services/core-control-plane/src/fdai/shared/contracts/action.py", "operator"),
        ("tools/architecture-diagrams/assets/resource.svg", "operator"),
        ("eval/golden-dataset/example.json", "python"),
        ("eval/golden-dataset/example.json", "operator"),
        ("eval/golden-dataset/example.json", "evaluation"),
        ("evaluation-sdk/src/fdai_evaluation_sdk/client.py", "evaluation"),
        ("benchmarks/cybergym/tests/test_adapter.py", "evaluation"),
        ("pyproject.toml", "dependencies"),
        ("services/core-control-plane/tests/scenarios/v1/example.json", "scenarios"),
    ],
)
def test_change_scope_classification_selects_owning_ci_surface(
    path: str,
    field: str,
) -> None:
    assert getattr(classify_paths([path]), field)


def test_ci_workflow_change_runs_every_scoped_surface() -> None:
    assert all(classify_paths([".github/workflows/ci.yml"]))


@pytest.mark.parametrize(
    "path",
    [
        ".github/copilot-instructions.md",
        ".github/skills/ci-diagnosis/SKILL.md",
        ".github/prompts/verify.prompt.md",
        ".github/agents/integration-validator.agent.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
    ],
)
def test_developer_guidance_selects_only_documentation(path: str) -> None:
    assert classify_paths([path]) == ChangeScope(False, True, False, False, False, False, False)


def test_guidance_assets_and_unknown_files_still_fail_safe() -> None:
    assert all(classify_paths([".github/skills/example/run.py"]))
    assert all(classify_paths([".github/skills/example/config.yaml"]))


def test_backend_only_changes_do_not_run_independent_frontend_and_evaluation_suites() -> None:
    paths = ["services/core-control-plane/src/fdai/core/risk_gate/gate.py"]
    scope = classify_paths(paths)
    assert scope.python and scope.docs
    assert not scope.operator and not scope.evaluation
    mixed = classify_paths([*paths, "console/src/app.tsx", ".github/skills/example/SKILL.md"])
    assert mixed.python and mixed.docs and mixed.operator


@pytest.mark.parametrize("path", ["pyproject.toml", "uv.lock", "Makefile"])
def test_shared_build_inputs_keep_consumer_suites(path: str) -> None:
    scope = classify_paths([path])
    assert scope.python and scope.operator and scope.evaluation


def test_every_system_knowledge_catalog_source_selects_derived_source_validation() -> None:
    root = Path(__file__).resolve().parents[3]
    catalog = json.loads(
        (
            root / "services/system-knowledge-service/src/"
            "fdai_system_knowledge_service/data/catalog.json"
        ).read_text(encoding="utf-8")
    )
    source_paths = {source["path"] for record in catalog["records"] for source in record["sources"]}

    assert source_paths
    assert all(classify_paths([path]).docs for path in source_paths)


def test_unclassified_path_fails_safe_to_every_ci_surface() -> None:
    assert all(classify_paths(["new-subsystem/unknown.input"]))
    assert all(classify_paths(["docs/known.md", "new-subsystem/unknown.input"]))
