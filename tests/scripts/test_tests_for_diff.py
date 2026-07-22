"""Regression tests for diff-scoped pytest selection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from scripts.quality.ci.resolve_test_scope import _PYTHON_FILES

_ROOT = Path(__file__).resolve().parents[2]
_SELECTOR = _ROOT / "scripts" / "automation" / "tests-for-diff.sh"


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
        "src/fdai/core/risk_gate",
        "tests/composition",
        "tests/config",
        "tests/conversation",
        "tests/core/risk_gate",
        "tests/delivery/dev_operations_gateway",
        "tests/persistence",
        "tests/rule_catalog",
        "tests/scripts",
        "tests/shared/contracts",
        "tests/shared/providers",
        "tests/tools",
        "tests/verticals",
    ):
        directory = tmp_path / path
        directory.mkdir(parents=True)
        (directory / ".keep").write_text("\n", encoding="utf-8")
    (tmp_path / "tests" / "conftest.py").write_text("\n", encoding="utf-8")
    assert _run(tmp_path, "git", "add", ".").returncode == 0
    assert _run(tmp_path, "git", "commit", "--quiet", "-m", "test fixture").returncode == 0
    return tmp_path


def test_selects_tests_for_untracked_python_source(git_repo: Path) -> None:
    consumer = git_repo / "tests" / "verticals" / "test_risk_consumer.py"
    consumer.write_text("from fdai.core.risk_gate import new_rule\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add consumer").returncode == 0
    source = git_repo / "src" / "fdai" / "core" / "risk_gate" / "new_rule.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "tests/core/risk_gate",
        "tests/verticals/test_risk_consumer.py",
    ]


def test_shared_contract_change_falls_back_to_full_suite(git_repo: Path) -> None:
    source = git_repo / "src" / "fdai" / "shared" / "contracts" / "models.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_shared_provider_change_falls_back_to_full_suite(git_repo: Path) -> None:
    source = git_repo / "src" / "fdai" / "shared" / "providers" / "state_store.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_composition_package_change_falls_back_to_full_suite(git_repo: Path) -> None:
    source = git_repo / "src" / "fdai" / "composition" / "container.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_selects_tests_for_top_level_delivery_source(git_repo: Path) -> None:
    source = git_repo / "delivery" / "dev_operations_gateway" / "gateway.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests/delivery/dev_operations_gateway"]


def test_selects_tests_for_tool_source(git_repo: Path) -> None:
    consumer = git_repo / "tests" / "conversation" / "test_tool_consumer.py"
    consumer.write_text("from tools import baseline_run\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add tool consumer").returncode == 0
    source = git_repo / "tools" / "baseline_run.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "tests/conversation/test_tool_consumer.py",
        "tests/tools",
    ]


def test_unknown_python_source_falls_back_to_full_suite(git_repo: Path) -> None:
    (git_repo / "unknown.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_missing_mirrored_test_directory_falls_back_to_full_suite(git_repo: Path) -> None:
    source = git_repo / "src" / "fdai" / "new_area" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_cross_subsystem_rename_selects_old_and_new_tests(git_repo: Path) -> None:
    old_source = git_repo / "src" / "fdai" / "core" / "risk_gate" / "moved.py"
    old_source.write_text("VALUE = 1\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", ".").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "add source").returncode == 0

    new_source = git_repo / "src" / "fdai" / "delivery" / "dev_operations_gateway" / "moved.py"
    new_source.parent.mkdir(parents=True)
    assert _run(git_repo, "git", "mv", str(old_source), str(new_source)).returncode == 0

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "tests/core/risk_gate",
        "tests/delivery/dev_operations_gateway",
    ]


@pytest.mark.parametrize(
    "path",
    (
        "rule-catalog/catalog/rule.yaml",
        "src/fdai/rule_catalog/schema.py",
    ),
)
def test_catalog_change_falls_back_to_full_suite(git_repo: Path, path: str) -> None:
    catalog = git_repo / path
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("VALUE = 1\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_root_config_change_falls_back_to_full_suite(git_repo: Path) -> None:
    config = git_repo / "config" / "rbac-groups.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("groups: []\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_policy_change_falls_back_to_full_suite(git_repo: Path) -> None:
    policy = git_repo / "policies" / "compute" / "deny.rego"
    policy.parent.mkdir(parents=True)
    policy.write_text("package fdai.test\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


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
    assert result.stdout.splitlines() == ["tests/scripts"]


def test_global_test_configuration_falls_back_to_full_suite(git_repo: Path) -> None:
    (git_repo / "tests" / "conftest.py").write_text("GLOBAL = True\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


@pytest.mark.parametrize(
    "path",
    (
        "tests/scenarios/fixture.json",
        "src/fdai/delivery/read_api/schema.json",
    ),
)
def test_python_resource_change_falls_back_to_full_suite(git_repo: Path, path: str) -> None:
    resource = git_repo / path
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text("{}\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


@pytest.mark.parametrize("path", sorted(_PYTHON_FILES))
def test_ci_python_input_falls_back_to_full_suite(git_repo: Path, path: str) -> None:
    input_file = git_repo / path
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text("input\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests"]


def test_parent_test_directory_suppresses_duplicate_child_path(git_repo: Path) -> None:
    script = git_repo / "scripts" / "automation" / "helper.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    test_file = git_repo / "tests" / "scripts" / "test_changed.py"
    test_file.write_text("def test_changed(): pass\n", encoding="utf-8")

    result = _run(git_repo, "bash", str(_SELECTOR))

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["tests/scripts"]


def test_run_uses_uv_managed_pytest(git_repo: Path) -> None:
    test_file = git_repo / "tests" / "scripts" / "test_changed.py"
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
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "run pytest -q -m not integration --no-cov tests/scripts/test_changed.py"
    ]
    assert "integration tests skipped" in result.stderr


def test_run_accepts_integration_only_selection_without_database(git_repo: Path) -> None:
    test_file = git_repo / "tests" / "scripts" / "test_changed.py"
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
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "run pytest -q -m not integration --no-cov tests/scripts/test_changed.py",
        "run pytest --collect-only -q -m integration --no-cov tests/scripts/test_changed.py",
    ]
    assert "FDAI_DATABASE_URL unset; integration tests skipped" in result.stderr


def test_run_executes_selected_integration_tests_with_database(git_repo: Path) -> None:
    test_file = git_repo / "tests" / "scripts" / "test_changed.py"
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
    }

    result = _run(git_repo, "bash", str(_SELECTOR), "--run", env=env)

    assert result.returncode == 0, result.stderr
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "run pytest -q -m not integration --no-cov tests/scripts/test_changed.py",
        "run pytest -q -m integration --no-cov tests/scripts/test_changed.py",
    ]


def test_makefile_exposes_changed_test_target() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "test-changed:" in makefile
    assert "scripts/automation/tests-for-diff.sh --run $(DIFF)" in makefile
