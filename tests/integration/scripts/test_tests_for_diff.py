"""Regression tests for diff-scoped pytest selection."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts.quality.ci.resolve_test_scope import _PYTHON_FILES

_ROOT = Path(__file__).resolve().parents[3]
_SELECTOR = _ROOT / "scripts" / "automation" / "tests-for-diff.sh"
_SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
_ALL_TEST_ROOTS = [
    "packages/service-contracts/tests",
    "services/core-control-plane/tests",
    "services/document-ingestion-api/tests",
    "services/document-processing-worker/tests",
    "services/isolated-executor/tests",
    "services/operator-service/tests",
    "tests/integration",
]
_SCRIPT_TEST_ROOT = "tests/integration/scripts"


def _core_source(repo: Path, *parts: str) -> Path:
    return repo.joinpath("services", "core-control-plane", "src", "fdai", *parts)


def _core_test(repo: Path, *parts: str) -> Path:
    return repo.joinpath("services", "core-control-plane", "tests", *parts)


def _integration_test(repo: Path, *parts: str) -> Path:
    return repo.joinpath("tests", "integration", *parts)


def _assert_full_suite(result: subprocess.CompletedProcess[str]) -> None:
    assert result.stdout.splitlines() == _ALL_TEST_ROOTS


def _run(
    repo: Path, *command: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed script with test-controlled arguments
        command,
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    assert _run(tmp_path, "git", "init", "--quiet").returncode == 0
    assert _run(tmp_path, "git", "config", "user.email", "tests@example.com").returncode == 0
    assert _run(tmp_path, "git", "config", "user.name", "FDAI Tests").returncode == 0

    for path in (
        "delivery/dev_operations_gateway",
        "extensions/code-assurance/tests",
        "services/core-control-plane/src/fdai/core/risk_gate",
        "services/core-control-plane/tests/composition",
        "services/core-control-plane/tests/config",
        "services/core-control-plane/tests/conversation",
        "services/core-control-plane/tests/core/risk_gate",
        "services/core-control-plane/tests/delivery/dev_operations_gateway",
        "services/core-control-plane/tests/persistence",
        "services/core-control-plane/tests/rule_catalog",
        "tests/integration/scripts",
        "services/core-control-plane/tests/shared/contracts",
        "services/core-control-plane/tests/shared/providers",
        "services/core-control-plane/tests/tools",
        "services/core-control-plane/tests/verticals",
    ):
        directory = tmp_path / path
        directory.mkdir(parents=True)
        (directory / ".keep").write_text("\n", encoding="utf-8")
    for relative in _ALL_TEST_ROOTS:
        directory = tmp_path / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".root-keep").write_text("\n", encoding="utf-8")
    (tmp_path / "tests" / "integration" / "conftest.py").write_text("\n", encoding="utf-8")
    assert _run(tmp_path, "git", "add", ".").returncode == 0
    assert _run(tmp_path, "git", "commit", "--quiet", "-m", "test fixture").returncode == 0
    return tmp_path


def _commit_final_test_layout(repo: Path) -> None:
    for service_id in _SERVICE_IDS:
        test_root = repo / "services" / service_id / "tests"
        test_root.mkdir(parents=True, exist_ok=True)
        (test_root / ".keep").write_text("\n", encoding="utf-8")
    contract_tests = repo / "packages" / "service-contracts" / "tests"
    contract_tests.mkdir(parents=True, exist_ok=True)
    (contract_tests / ".keep").write_text("\n", encoding="utf-8")
    integration = repo / "tests" / "integration"
    integration.mkdir(exist_ok=True)
    (integration / ".keep").write_text("\n", encoding="utf-8")
    (repo / ".final-test-layout").write_text("present\n", encoding="utf-8")
    assert _run(repo, "git", "add", ".").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", "add final test layout").returncode == 0


def test_selects_service_owned_and_integration_consumers(git_repo: Path) -> None:
    _commit_final_test_layout(git_repo)
    consumer = git_repo / "tests" / "integration" / "test_risk_consumer.py"
    consumer.write_text("from fdai.core.risk_gate import new_rule\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add consumer").returncode == 0
    source = (
        git_repo
        / "services"
        / "core-control-plane"
        / "src"
        / "fdai"
        / "core"
        / "risk_gate"
        / "new_rule.py"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "services/core-control-plane/tests",
        "tests/integration/test_risk_consumer.py",
    ]


def test_contract_package_change_selects_every_owned_test_root(git_repo: Path) -> None:
    _commit_final_test_layout(git_repo)
    source = (
        git_repo / "packages" / "service-contracts" / "src" / "fdai_service_contracts" / "models.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "packages/service-contracts/tests",
        "services/core-control-plane/tests",
        "services/document-ingestion-api/tests",
        "services/document-processing-worker/tests",
        "services/isolated-executor/tests",
        "services/operator-service/tests",
        "tests/integration",
    ]


def test_script_change_selects_moved_integration_script_tests(git_repo: Path) -> None:
    _commit_final_test_layout(git_repo)
    script = git_repo / "scripts" / "automation" / "helper.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests/integration/scripts"]


def test_developer_workflow_change_selects_only_integration_script_tests(
    git_repo: Path,
) -> None:
    _commit_final_test_layout(git_repo)
    script = git_repo / "scripts" / "automation" / "developer-workflow.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests/integration/scripts"]


def test_selects_tests_for_untracked_python_source(git_repo: Path) -> None:
    consumer = _core_test(git_repo, "verticals", "test_risk_consumer.py")
    consumer.write_text("from fdai.core.risk_gate import new_rule\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add consumer").returncode == 0
    source = _core_source(git_repo, "core", "risk_gate", "new_rule.py")
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["services/core-control-plane/tests"]


def test_shared_contract_change_falls_back_to_full_suite(git_repo: Path) -> None:
    source = _core_source(git_repo, "shared", "contracts", "models.py")
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_shared_provider_change_falls_back_to_full_suite(git_repo: Path) -> None:
    source = _core_source(git_repo, "shared", "providers", "state_store.py")
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_composition_package_change_falls_back_to_full_suite(git_repo: Path) -> None:
    source = _core_source(git_repo, "composition", "container.py")
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_selects_tests_for_top_level_delivery_source(git_repo: Path) -> None:
    source = git_repo / "delivery" / "dev_operations_gateway" / "gateway.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "services/core-control-plane/tests/delivery/dev_operations_gateway"
    ]


def test_selects_tests_for_tool_source(git_repo: Path) -> None:
    consumer = _core_test(git_repo, "conversation", "test_tool_consumer.py")
    consumer.write_text("from tools import baseline_run\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add tool consumer").returncode == 0
    source = git_repo / "tools" / "baseline_run.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "services/core-control-plane/tests/conversation/test_tool_consumer.py",
        "services/core-control-plane/tests/tools",
    ]


def test_selects_code_assurance_tests_for_packaged_skill_change(git_repo: Path) -> None:
    skill = git_repo / "extensions" / "code-assurance" / "assets" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("review instructions\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["extensions/code-assurance/tests"]


def test_unknown_python_source_falls_back_to_full_suite(git_repo: Path) -> None:
    (git_repo / "unknown.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_unknown_core_submodule_selects_core_owned_suite(git_repo: Path) -> None:
    source = _core_source(git_repo, "new_area", "module.py")
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["services/core-control-plane/tests"]


def test_cross_subsystem_rename_selects_old_and_new_tests(git_repo: Path) -> None:
    old_source = _core_source(git_repo, "core", "risk_gate", "moved.py")
    old_source.write_text("VALUE = 1\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add source").returncode == 0

    new_source = _core_source(git_repo, "delivery", "dev_operations_gateway", "moved.py")
    new_source.parent.mkdir(parents=True)
    assert _run(git_repo, "git", "mv", str(old_source), str(new_source)).returncode == 0

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["services/core-control-plane/tests"]


@pytest.mark.parametrize(
    "path",
    (
        "rule-catalog/catalog/rule.yaml",
        "services/core-control-plane/src/fdai/rule_catalog/schema.py",
    ),
)
def test_catalog_change_falls_back_to_full_suite(git_repo: Path, path: str) -> None:
    catalog = git_repo / path
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_root_config_change_falls_back_to_full_suite(git_repo: Path) -> None:
    config = git_repo / "config" / "rbac-groups.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("groups: []\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_service_decomposition_change_selects_owned_tests(git_repo: Path) -> None:
    config = git_repo / "config" / "service-decomposition.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"schema_version": 1}\n', encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [_SCRIPT_TEST_ROOT]


def test_policy_change_falls_back_to_full_suite(git_repo: Path) -> None:
    policy = git_repo / "policies" / "compute" / "deny.rego"
    policy.parent.mkdir(parents=True)
    policy.write_text("package fdai.test\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


@pytest.mark.parametrize(
    "path",
    (
        "scripts/lib/design-routes.json",
        "scripts/lib/framework-surface.txt",
        "scripts/quality/repository/punctuation-baseline.txt",
        "scripts/quality/architecture/.check-subsystem-fanout.allowlist",
    ),
)
def test_selects_script_tests_for_behavior_support_data(git_repo: Path, path: str) -> None:
    support_file = git_repo / path
    support_file.parent.mkdir(parents=True, exist_ok=True)
    support_file.write_text("support\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [_SCRIPT_TEST_ROOT]


def test_global_test_configuration_falls_back_to_full_suite(git_repo: Path) -> None:
    _integration_test(git_repo, "conftest.py").write_text("GLOBAL = True\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


@pytest.mark.parametrize(
    "path",
    (
        "services/core-control-plane/tests/scenarios/fixture.json",
        "services/core-control-plane/src/fdai/delivery/operator_api/schema.json",
    ),
)
def test_python_resource_change_falls_back_to_full_suite(git_repo: Path, path: str) -> None:
    resource = git_repo / path
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text("{}\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


@pytest.mark.parametrize("path", sorted(_PYTHON_FILES))
def test_ci_python_input_falls_back_to_full_suite(git_repo: Path, path: str) -> None:
    input_file = git_repo / path
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text("input\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_migration_change_falls_back_to_full_suite(git_repo: Path) -> None:
    migration = git_repo / "alembic" / "versions" / "revision.py"
    migration.parent.mkdir(parents=True)
    migration.write_text("revision = 'example'\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    _assert_full_suite(result)


def test_parent_test_directory_suppresses_duplicate_child_path(git_repo: Path) -> None:
    script = git_repo / "scripts" / "automation" / "helper.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [_SCRIPT_TEST_ROOT]


def test_impact_resolver_failure_aborts_selection(git_repo: Path) -> None:
    source = _core_source(git_repo, "core", "risk_gate", "new_rule.py")
    source.write_text("VALUE = 1\n", encoding="utf-8")
    failing_resolver = git_repo.parent / f"{git_repo.name}-failing-resolver.py"
    failing_resolver.write_text("raise SystemExit(7)\n", encoding="utf-8")
    env = {
        **os.environ,
        "FDAI_TEST_IMPACT_RESOLVER": str(failing_resolver),
    }

    result = _run(git_repo, "bash", str(_SELECTOR), env=env)

    assert result.returncode == 7
    assert "impact resolver failed" in result.stderr


def test_broad_import_impact_uses_service_owned_suite(git_repo: Path, tmp_path: Path) -> None:
    owned_test = _core_test(git_repo, "core", "risk_gate", "test_one.py")
    owned_test.parent.mkdir(parents=True, exist_ok=True)
    owned_test.write_text("def test_one(): pass\n", encoding="utf-8")
    external_test = _core_test(git_repo, "verticals", "test_two.py")
    external_test.write_text("def test_two(): pass\n", encoding="utf-8")
    impact_resolver = tmp_path / "impact.py"
    impact_resolver.write_text(
        "print('services/core-control-plane/tests/core/risk_gate/test_one.py')\nprint('services/core-control-plane/tests/verticals/test_two.py')\n",
        encoding="utf-8",
    )
    ownership_resolver = tmp_path / "ownership.py"
    ownership_resolver.write_text(
        "print('services/core-control-plane/tests/core/risk_gate')\n", encoding="utf-8"
    )
    assert _run(git_repo, "git", "add", "impact.py", "ownership.py").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add resolvers").returncode == 0
    source = _core_source(git_repo, "core", "risk_gate", "new_rule.py")
    source.write_text("VALUE = 1\n", encoding="utf-8")
    env = {
        **os.environ,
        "FDAI_TEST_IMPACT_RESOLVER": str(impact_resolver),
        "FDAI_TEST_OWNERSHIP_RESOLVER": str(ownership_resolver),
        "FDAI_TEST_IMPACT_SERVICE_THRESHOLD": "2",
    }

    result = _run(git_repo, "bash", str(_SELECTOR), env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["services/core-control-plane/tests"]
    assert "compressed with service-owned suites" in result.stderr


def test_run_uses_uv_managed_pytest(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_DATABASE_URL": "",
    }
    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    command = args_file.read_text(encoding="utf-8").strip()
    assert "run pytest -q -m not integration --no-cov --durations=25" in command
    assert command.endswith("tests/integration/scripts/test_changed.py")
    assert "integration tests skipped" in result.stderr


def test_run_prefers_current_checkout_over_inherited_pythonpath(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    pythonpath_file = git_repo / "pytest-pythonpath.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\n" "$PYTHONPATH" > "$PYTHONPATH_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    inherited = str(git_repo.parent / "other-worktree" / "src")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PYTHONPATH": inherited,
        "PYTHONPATH_FILE": str(pythonpath_file),
        "FDAI_DATABASE_URL": "",
    }

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    assert pythonpath_file.read_text(encoding="utf-8").strip().split(":") == [
        str(git_repo / "services" / "core-control-plane" / "src"),
        inherited,
    ]


def test_run_accepts_integration_only_selection_without_database(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
printf "%s\\n" "$*" >> "$UV_ARGS_FILE"
case "$*" in
    *--collect-only*) exit 0 ;;
    *) exit 5 ;;
esac
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_DATABASE_URL": "",
    }
    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    commands = args_file.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert "run pytest -q -m not integration --no-cov --durations=25" in commands[0]
    assert "run pytest --collect-only -q -m integration --no-cov" in commands[1]
    assert all(
        command.endswith("tests/integration/scripts/test_changed.py") for command in commands
    )
    assert "integration tests skipped" in result.stderr
    assert "FDAI_CHANGED_TEST_INTEGRATION=1" in result.stderr


def test_run_executes_selected_integration_tests_with_database(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
        "FDAI_CHANGED_TEST_INTEGRATION": "1",
    }

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    commands = args_file.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert "run pytest -q -m not integration --no-cov --durations=25" in commands[0]
    assert "run pytest -q -m integration --no-cov --durations=25" in commands[1]
    assert all(
        command.endswith("tests/integration/scripts/test_changed.py") for command in commands
    )


def test_run_isolates_runtime_env_and_readds_only_integration_database(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    env_file = git_repo / "pytest-env.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s|%s|%s|%s\\n" "${FDAI_DATABASE_URL-unset}" '
        '"${FDAI_RUNTIME_LOCK_FILE-unset}" "${FDAI_RUNTIME_LOCAL_AZURE_CLI-unset}" '
        '"${RUNTIME_ENV-unset}" >> "$PYTEST_ENV_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PYTEST_ENV_FILE": str(env_file),
        "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
        "FDAI_CHANGED_TEST_INTEGRATION": "1",
        "FDAI_RUNTIME_LOCK_FILE": str(git_repo / ".fdai" / "core-runtime.lock"),
        "FDAI_RUNTIME_LOCAL_AZURE_CLI": "1",
        "RUNTIME_ENV": "dev",
    }

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "unset|unset|unset|unset",
        "postgresql://example.invalid/fdai|unset|unset|unset",
    ]


def test_run_does_not_use_database_without_explicit_integration_opt_in(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_DATABASE_URL": "postgresql://example.invalid/shared-runtime",
    }
    env.pop("FDAI_CHANGED_TEST_INTEGRATION", None)

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    command = args_file.read_text(encoding="utf-8").strip()
    assert "run pytest -q -m not integration --no-cov --durations=25" in command
    assert command.endswith("tests/integration/scripts/test_changed.py")
    assert "integration tests skipped" in result.stderr
    assert "dedicated validation FDAI_DATABASE_URL" in result.stderr


def test_run_parallelizes_broad_non_integration_selection(git_repo: Path) -> None:
    for index in range(20):
        test_file = _integration_test(git_repo, "scripts", f"test_changed_{index}.py")
        test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    shard_dir = git_repo / "changed-test-shards"
    cache_dir = git_repo / "changed-test-cache"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_DATABASE_URL": "",
        "FDAI_CHANGED_TEST_SHARD_DIR": str(shard_dir),
        "FDAI_CHANGED_TEST_CACHE_DIR": str(cache_dir),
        "FDAI_PYTEST_MAX_WORKERS": "4",
    }

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    commands = args_file.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 4
    for command in commands:
        assert "-m not integration" in command
        assert "--durations=25" in command
        assert "-p scripts.quality.ci.pytest_shard" in command
    assert {
        index
        for index in range(1, 5)
        if any(f"cache_dir={cache_dir}/shard-{index}" in command for command in commands)
    } == {1, 2, 3, 4}
    summary = json.loads((shard_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["shard_count"] == 4
    assert [shard["status"] for shard in summary["shards"]] == [0, 0, 0, 0]

    retried = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert retried.returncode == 0, retried.stderr
    assert args_file.read_text(encoding="utf-8").splitlines() == commands
    retry_summary = json.loads((shard_dir / "summary.json").read_text(encoding="utf-8"))
    assert [shard["cached"] for shard in retry_summary["shards"]] == [True] * 4


def test_run_parallelizes_full_suite_fallback(git_repo: Path) -> None:
    (git_repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_DATABASE_URL": "",
    }
    env.pop("FDAI_PYTEST_MAX_WORKERS", None)

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    commands = args_file.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 4
    assert all("-p scripts.quality.ci.pytest_shard" in command for command in commands)
    assert all(command.endswith(" " + " ".join(_ALL_TEST_ROOTS)) for command in commands)


def test_run_combines_included_failure_with_delta_and_external_cache(git_repo: Path) -> None:
    prior_failure = _integration_test(git_repo, "scripts", "test_prior.py")
    prior_failure.write_text("def test_prior(): pass\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "prior test").returncode == 0
    changed_test = _integration_test(git_repo, "scripts", "test_changed.py")
    changed_test.write_text("def test_changed(): pass\n", encoding="utf-8")
    bin_dir = git_repo / "bin"
    bin_dir.mkdir()
    args_file = git_repo / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_ARGS_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    cache_dir = git_repo / "shared-pytest-cache"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_ARGS_FILE": str(args_file),
        "FDAI_CHANGED_TEST_CACHE_DIR": str(cache_dir),
    }

    result = _run(
        git_repo,
        "bash",
        str(_SELECTOR),
        "--run",
        "--include-test",
        "tests/integration/scripts/test_prior.py::test_prior",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    command = args_file.read_text(encoding="utf-8").splitlines()[0]
    assert f"-o cache_dir={cache_dir}" in command
    assert "tests/integration/scripts/test_changed.py" in command
    assert "tests/integration/scripts/test_prior.py::test_prior" in command


def test_run_rejects_invalid_parallel_threshold(git_repo: Path) -> None:
    test_file = _integration_test(git_repo, "scripts", "test_changed.py")
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")
    env = {
        **os.environ,
        "FDAI_CHANGED_TEST_PARALLEL_THRESHOLD": "zero",
    }

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 2
    assert "must be a positive integer" in result.stderr


def test_makefile_exposes_changed_test_target() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "test-changed:" in makefile
    assert "scripts/automation/tests-for-diff.sh --run $(DIFF)" in makefile
