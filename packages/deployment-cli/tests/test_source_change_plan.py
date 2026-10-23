from __future__ import annotations

import subprocess
from pathlib import Path

from fdai_deployment_cli import cli
from fdai_deployment_cli.source_change_plan import plan_git_changes, source_change_plan

BASE = "a" * 40
HEAD = "b" * 40


def test_routes_non_runtime_and_single_service_changes() -> None:
    no_deploy = source_change_plan(
        [
            "docs/user-guide/get-started.md",
            "services/operator-service/tests/test_main.py",
            "console/tests/e2e/dashboard.spec.ts",
        ],
        base_commit=BASE,
        head_commit=HEAD,
    )
    service = source_change_plan(
        ["services/operator-service/src/fdai_operator_service/main.py"],
        base_commit=BASE,
        head_commit=HEAD,
    )

    assert no_deploy["lane"] == "no-deploy"
    assert service["lane"] == "single-service-update"
    assert service["services"] == ["operator-service"]
    assert service["mutation_performed"] is False


def test_runtime_scenarios_require_both_core_profiles() -> None:
    result = source_change_plan(
        ["services/core-control-plane/tests/scenarios/replay.yaml"],
        base_commit=BASE,
        head_commit=HEAD,
    )

    assert result["lane"] == "full-release-required"
    assert result["services"] == ["core-control-plane"]
    assert result["unsupported_hot_path_targets"] == ["cost-governance"]


def test_routes_console_shared_and_infrastructure_changes_conservatively() -> None:
    assert (
        source_change_plan(["console/src/main.tsx"], base_commit=BASE, head_commit=HEAD)["lane"]
        == "console-update"
    )
    assert (
        source_change_plan(
            ["packages/service-contracts/src/fdai_service_contracts/events.py"],
            base_commit=BASE,
            head_commit=HEAD,
        )["lane"]
        == "full-release-required"
    )
    assert (
        source_change_plan(["infra/main.tf"], base_commit=BASE, head_commit=HEAD)["lane"]
        == "higher-lane-required"
    )


def test_routes_console_and_service_as_split_update() -> None:
    result = source_change_plan(
        [
            "console/src/main.tsx",
            "services/operator-service/src/fdai_operator_service/main.py",
        ],
        base_commit=BASE,
        head_commit=HEAD,
    )

    assert result["lane"] == "split-update-required"
    assert result["console_changed"] is True
    assert result["services"] == ["operator-service"]


def test_git_plan_and_cli_are_read_only(tmp_path: Path, capsys) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "user@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Example"], cwd=repository, check=True)
    path = repository / "services/operator-service/src/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "base"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    path.write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "head"],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    result = plan_git_changes(repository, base)
    exit_code = cli.main(
        [
            "provision",
            "source-change-plan",
            "--source",
            str(repository),
            "--base",
            base,
            "--output",
            "json",
        ]
    )

    assert result["lane"] == "single-service-update"
    assert exit_code == 0
    assert '"mutation_performed":false' in capsys.readouterr().out
