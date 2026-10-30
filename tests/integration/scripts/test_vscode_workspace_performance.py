from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_jsonc(path: Path) -> object:
    content = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    return json.loads(content)


def test_pylance_analyzes_owned_roots_without_background_indexing() -> None:
    settings = _load_jsonc(REPO_ROOT / ".vscode" / "settings.json")
    assert isinstance(settings, dict)

    assert "azureTerraform.languageServer" not in settings
    assert "liveServer.settings.host" not in settings
    assert "liveServer.settings.port" not in settings
    assert settings["python.analysis.include"] == [
        "alembic",
        "benchmarks/*/src",
        "delivery",
        "evaluation-sdk/src",
        "extensions/*/src",
        "packages/*/src",
        "scripts",
        "service-migrations",
        "services/*/src",
        "tools",
    ]
    assert settings["python.analysis.indexing"] is False
    assert settings["python.analysis.logLevel"] == "Warning"
    assert "python.analysis.nodeArguments" not in settings
    assert "python.analysis.nodeExecutable" not in settings
    assert settings["python.analysis.useLibraryCodeForTypes"] is False
    assert settings["python.analysis.userFileIndexFollowSymlinkedFolders"] is False


def test_workspace_uses_one_instruction_and_git_sync_path() -> None:
    settings = _load_jsonc(REPO_ROOT / ".vscode" / "settings.json")
    assert isinstance(settings, dict)

    assert settings["chat.contextUsage.enabled"] is True
    assert settings["chat.useNestedAgentsMdFiles"] is False
    assert settings["github.copilot.chat.summarizeAgentConversationHistory.enabled"] is True
    assert settings["github.copilot.chat.summarizeAgentConversationHistoryThreshold"] == 0.8
    assert settings["github.copilot.nextEditSuggestions.enabled"] is False
    assert settings["chat.hookFilesLocations"] == {
        ".github/hooks": True,
        ".claude/settings.local.json": False,
        ".claude/settings.json": False,
        "~/.agents/hooks": False,
        "~/.claude/settings.json": False,
        "~/.copilot/hooks": False,
    }
    assert settings["git.autofetch"] is False


def test_workspace_suppresses_non_actionable_terminal_alerts() -> None:
    settings = _load_jsonc(REPO_ROOT / ".vscode" / "settings.json")
    assert isinstance(settings, dict)

    assert settings["terminal.integrated.environmentChangesIndicator"] == "off"
    assert settings["terminal.integrated.showExitAlert"] is False


def test_hook_install_task_does_not_depend_on_the_terminal_shell() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    task = next(
        task for task in tasks["tasks"] if task["label"] == "hooks: install (core.hooksPath)"
    )

    assert task["type"] == "process"
    assert task["command"] == "git"
    assert task["args"] == ["config", "--local", "core.hooksPath", ".githooks"]
    assert task["options"] == {"cwd": "${workspaceFolder}"}
    assert task["runOptions"] == {"runOn": "folderOpen"}


@pytest.mark.parametrize("initialized", [True, False])
def test_hook_install_task_preserves_git_success_and_failure(
    tmp_path: Path, initialized: bool
) -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    task = next(
        task for task in tasks["tasks"] if task["label"] == "hooks: install (core.hooksPath)"
    )
    checkout = tmp_path / "checkout with spaces"
    checkout.mkdir()
    if initialized:
        subprocess.run(
            ["git", "init", "--quiet"],  # noqa: S607 - Git is the fixed test executable.
            cwd=checkout,
            check=True,
        )

    for _ in range(2):
        result = subprocess.run(  # noqa: S603 - tracked task against a temporary repository.
            [task["command"], *task["args"]],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
        )
        if initialized:
            assert result.returncode == 0, result.stderr
            config = subprocess.run(
                ["git", "config", "--local", "--get", "core.hooksPath"],  # noqa: S607
                cwd=checkout,
                capture_output=True,
                text=True,
                check=True,
            )
            assert config.stdout.strip() == ".githooks"
        else:
            assert result.returncode != 0
            assert result.stderr
            assert not result.stdout


def test_design_mocks_task_reports_started_and_reused_servers_as_ready() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    task = next(task for task in tasks["tasks"] if task["label"] == "design mocks: serve (5373)")

    assert task["command"] == "bash scripts/deployment/local/start-design-mocks.sh"
    assert task["options"]["cwd"] == "${workspaceFolder}"
    assert task["isBackground"] is True
    ready = re.compile(task["problemMatcher"]["background"]["endsPattern"])
    assert ready.search("Serving HTTP on 127.0.0.1 port 5373")
    assert ready.search("2026-01-01T00:00:00+00:00 service=design-mocks event=reused")
    assert not ready.search("service=other-server event=reused")


def test_workspace_exposes_explicit_complete_console_topology() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    tasks_by_label = {task["label"]: task for task in tasks["tasks"]}
    assert len(tasks_by_label) == len(tasks["tasks"]) == 33
    allowed_instance_policies = {
        "terminateNewest",
        "terminateOldest",
        "prompt",
        "warn",
        "silent",
    }
    assert {
        task["runOptions"]["instancePolicy"]
        for task in tasks["tasks"]
        if "instancePolicy" in task.get("runOptions", {})
    } <= allowed_instance_policies

    prepare_stack = tasks_by_label["console: prepare full stack"]
    assert prepare_stack["command"] == (
        "bash scripts/deployment/local/prepare-console-full-stack.sh "
        "--defer-authoritative-inventory --auth-mode browser-entra"
    )
    assert "dependsOn" not in prepare_stack
    assert prepare_stack["runOptions"] == {"instanceLimit": 1}

    removed_preparation_tasks = {
        "console: prepare local state",
        "console: prepare local runtime env",
        "console: refresh authoritative inventory",
        "console: refresh authoritative settings",
        "console: refresh authoritative catalogs",
        "console: prepare local Operator Service env",
        "console: prepare local independent service envs",
        "console: sync local Entra redirects",
    }
    assert removed_preparation_tasks.isdisjoint(tasks_by_label)

    preparation_script = (
        REPO_ROOT / "scripts" / "deployment" / "local" / "prepare-console-full-stack.sh"
    ).read_text(encoding="utf-8")
    preparation_stages = [
        "local-state",
        "runtime-environment",
        "authoritative-inventory",
        "authoritative-settings",
        "authoritative-catalogs",
        "service-environments",
        "entra-redirects",
    ]
    preparation_positions = []
    for stage in preparation_stages:
        match = re.search(
            rf"(?m)^\s*run_stage \\\n\s+{re.escape(stage)} \\\n",
            preparation_script,
        )
        assert match is not None
        preparation_positions.append(match.start())
    assert preparation_positions == sorted(preparation_positions)
    assert (
        preparation_script.index('bash "$repo_root/scripts/deployment/local/dev-up.sh"')
        < (preparation_positions[0])
    )

    full_stack = tasks_by_label["console: start full stack"]
    assert full_stack["dependsOrder"] == "sequence"
    assert full_stack["dependsOn"] == [
        "console: require primary worktree",
        "console: prepare full stack",
        "console: start local services",
    ]
    assert full_stack["runOptions"] == {
        "instanceLimit": 2,
        "instancePolicy": "silent",
    }

    start_guard = tasks_by_label["console: require primary worktree"]
    assert start_guard["type"] == "shell"
    assert "--git-dir" in start_guard["command"]
    assert "--git-common-dir" in start_guard["command"]
    assert "exit 75" in start_guard["command"]
    assert start_guard["problemMatcher"] == []

    folder_open_tasks = {
        task["label"]
        for task in tasks["tasks"]
        if task.get("runOptions", {}).get("runOn") == "folderOpen"
    }
    assert folder_open_tasks == {
        "hooks: install (core.hooksPath)",
        "git: auto-pull (background)",
    }

    assert "dev-access: configure VPN on folder open" not in tasks_by_label

    visible_tasks = {task["label"] for task in tasks["tasks"] if not task.get("hide", False)}
    assert visible_tasks == {
        "git: pull now (rebase, autostash)",
        "console: Playwright quick (desktop)",
        "docs site: serve (4321)",
        "design mocks: serve (5373)",
        "lifecycle: serve example hub (8090)",
        "lifecycle: serve example release hub (8091)",
        "console: prepare full stack",
        "console: start core runtime",
        "console: restart core runtime",
        "console: restart operator api",
        "console: start local services",
        "console: start full stack",
        "console: restart full stack",
        "console: start full stack (Azure CLI debug, Contributor)",
        "console: keep full stack ready (10m)",
        "console: wait full stack ready",
        "analyzer: run continuously (local)",
        "channel edge: Operator Slack and Teams (Local)",
        "conversation assurance: start supervisor",
        "conversation assurance: start census",
        "conversation assurance: start selected agent",
        "conversation assurance: status",
        "conversation assurance: stop",
        "conversation assurance: open latest report",
        "dev discuss: start or restart profiled services",
        "dev discuss: status",
        "dev discuss: snapshot selected service",
        "dev discuss: profile selected service (5s)",
    }

    assurance_supervisor = tasks_by_label["conversation assurance: start supervisor"]
    assert assurance_supervisor["options"]["env"] == {
        "FDAI_CONVERSATION_ASSURANCE_OPERATOR_URL": "http://127.0.0.1:8010",
        "FDAI_CONVERSATION_ASSURANCE_TOKEN_FILE": (
            "${workspaceFolder}/.fdai/conversation-assurance/operator-token"
        ),
    }

    docs_preview = tasks_by_label["docs site: serve (4321)"]
    assert docs_preview["command"] == "npm --prefix site run dev -- --host 127.0.0.1 --port 4321"
    assert docs_preview["options"] == {"cwd": "${workspaceFolder}"}
    assert docs_preview["isBackground"] is True
    assert docs_preview["runOptions"] == {"instanceLimit": 1}
    assert "dependsOn" not in docs_preview
    assert docs_preview["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "astro.*ready in",
        "endsPattern": r"Local.*http://127\.0\.0\.1:4321/",
    }

    core_runtime = tasks_by_label["console: start core runtime"]
    assert core_runtime["command"] == (
        "bash scripts/deployment/local/run-console-service.sh core-runtime --wait-ready"
    )
    assert core_runtime["isBackground"] is True
    assert core_runtime["runOptions"] == {
        "instanceLimit": 1,
        "instancePolicy": "silent",
    }
    assert core_runtime["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=core-runtime event=starting$",
        "endsPattern": "service=core-runtime event=(ready|failed)(?: |$)",
    }

    restart_core_runtime = tasks_by_label["console: restart core runtime"]
    assert restart_core_runtime["command"] == core_runtime["command"]
    assert restart_core_runtime["isBackground"] is True
    assert restart_core_runtime["runOptions"] == {
        "instanceLimit": 2,
        "instancePolicy": "silent",
    }
    assert restart_core_runtime["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=core-runtime event=starting$",
        "endsPattern": "service=core-runtime event=(ready|failed)(?: |$)",
    }

    restart_operator_api = tasks_by_label["console: restart operator api"]
    assert restart_operator_api["command"] == (
        "bash scripts/deployment/local/run-console-service.sh operator-api --wait-ready"
    )
    assert restart_operator_api["isBackground"] is True
    assert restart_operator_api["options"]["env"] == {
        "FDAI_CONSOLE_EXPECTED_AUTH_MODE": "browser-entra"
    }
    assert restart_operator_api["runOptions"] == {
        "instanceLimit": 2,
        "instancePolicy": "silent",
    }
    assert restart_operator_api["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=operator-api event=starting$",
        "endsPattern": "service=operator-api event=(ready|failed)(?: |$)",
    }

    local_services = tasks_by_label["console: start local services"]
    assert local_services["command"] == (
        "bash scripts/deployment/local/start-console-services.sh --auth-mode browser-entra"
    )
    assert local_services["hide"] is False
    assert local_services["isBackground"] is True
    assert "dependsOn" not in local_services
    assert local_services["runOptions"] == {
        "instanceLimit": 2,
        "instancePolicy": "silent",
    }
    assert local_services["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=console-stack event=starting$",
        "endsPattern": "service=console-stack event=(ready|failed)(?: |$)",
    }
    assert local_services["presentation"]["close"] is True

    restart_stack = tasks_by_label["console: restart full stack"]
    assert restart_stack["command"] == (
        "bash scripts/deployment/local/restart-console-services.sh --auth-mode browser-entra"
    )
    assert "dependsOn" not in restart_stack
    restart_script = (
        REPO_ROOT / "scripts/deployment/local/restart-console-services.sh"
    ).read_text()
    assert "git rev-parse --path-format=absolute --git-dir" in restart_script
    assert "git rev-parse --path-format=absolute --git-common-dir" in restart_script
    assert restart_script.index('if [[ "$git_dir" != "$common_dir" ]]') < restart_script.index(
        'bash "$repo_root/scripts/deployment/local/stop-console-services.sh"'
    )
    assert restart_stack["isBackground"] is True
    assert restart_stack["runOptions"] == {"instanceLimit": 2, "instancePolicy": "silent"}
    assert (
        restart_stack["problemMatcher"]["background"]
        == local_services["problemMatcher"]["background"]
    )

    cli_prepare = tasks_by_label["console: prepare full stack (Azure CLI debug, Contributor)"]
    assert cli_prepare["command"].endswith("--auth-mode azure-cli")
    assert cli_prepare["hide"] is True
    cli_services = tasks_by_label["console: start local services (Azure CLI debug)"]
    assert cli_services["command"].endswith("--auth-mode azure-cli")
    assert cli_services["hide"] is True
    cli_stack = tasks_by_label["console: start full stack (Azure CLI debug, Contributor)"]
    assert cli_stack["dependsOn"] == [
        "console: require primary worktree",
        "console: prepare full stack (Azure CLI debug, Contributor)",
        "console: start local services (Azure CLI debug)",
    ]

    wait_ready = tasks_by_label["console: wait full stack ready"]
    assert "run-bounded-command.py" in wait_ready["command"]
    assert "--timeout-seconds 15" in wait_ready["command"]
    assert wait_ready["command"].endswith("developer-workflow.py local-services --wait-seconds 10")
    assert wait_ready["runOptions"] == {
        "instanceLimit": 1,
        "instancePolicy": "silent",
    }

    watchdog = tasks_by_label["console: keep full stack ready (10m)"]
    assert watchdog["command"] == ("bash scripts/deployment/local/watch-console-services.sh")
    assert watchdog["dependsOrder"] == "sequence"
    assert watchdog["dependsOn"] == ["console: require primary worktree"]
    assert watchdog["isBackground"] is True
    assert watchdog["runOptions"] == {
        "instanceLimit": 1,
        "instancePolicy": "silent",
    }
    assert watchdog["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=console-watchdog event=started",
        "endsPattern": "service=console-watchdog event=started",
    }

    removed_service_tasks = {
        "console: Core Control Plane (Local Docker)",
        "console: Operator API (Local Entra)",
        "console: Document Ingestion API (Local Docker)",
        "console: Document Processing Worker (Local Docker)",
        "console: Isolated Executor (Local Shadow)",
        "console: Inventory Reconciliation (Local)",
        "console: Observation Campaign (Local)",
        "console: frontend (Browser Entra)",
        "console: verify local services",
    }
    assert removed_service_tasks.isdisjoint(tasks_by_label)

    supervisor_script = (
        REPO_ROOT / "scripts" / "deployment" / "local" / "start-console-services.sh"
    ).read_text(encoding="utf-8")
    managed_services = (
        "core-runtime",
        "operator-api",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        "cost-governance-analytics",
        "inventory-reconciliation",
        "observation-campaign",
        "console-frontend",
        "manual-studio",
    )
    for service_name in managed_services:
        assert f"  {service_name}\n" in supervisor_script
    assert "run-console-service.sh" in supervisor_script
    assert "developer-workflow.py" in supervisor_script
    assert "local-services" in supervisor_script
    assert supervisor_script.index("event=started") < supervisor_script.index(
        '--wait-seconds "$readiness_seconds"'
    )
    assert 'readiness_seconds="${FDAI_CONSOLE_START_READINESS_SECONDS:-180}"' in (supervisor_script)
    assert "run-bounded-command.py" in supervisor_script
    assert "readiness_budget_seconds=$((readiness_seconds + 5))" in supervisor_script
    assert "require_managed_locks" in supervisor_script
    assert 'flock -n -E 75 "$lock_file" true' in supervisor_script
    assert "service=console-stack event=ready" in supervisor_script

    service_script = (
        REPO_ROOT / "scripts" / "deployment" / "local" / "run-console-service.sh"
    ).read_text(encoding="utf-8")
    assert "local-service-input-digest.py" in service_script
    assert "console/.env.local" in service_script
    assert 'export FDAI_LOCAL_SERVICE_INPUT_DIGEST="$input_digest"' in service_script
    assert "export FDAI_LOCAL_SERVICE_RESTART_STALE=1" in service_script
    assert "export FDAI_LOCAL_SERVICE_REUSE_EXISTING=1" in service_script
    assert "digest_inputs+=(rule-catalog)" in service_script
    assert '--only "$service"' in service_script
    assert service_script.index('--only "$service"') < service_script.index(
        'write_task_marker "ready"'
    )
    assert "PORT=5474" in service_script
    assert "tools/manual-studio" in service_script
    for service_name in (*managed_services, "operator-channel-edge"):
        assert service_name in service_script

    assert "FDAI_PANTHEON_HEARTBEAT_SECONDS=2" in service_script

    assert "channel edge: prepare local env" not in tasks_by_label
    channel_edge = tasks_by_label["channel edge: Operator Slack and Teams (Local)"]
    assert "dependsOn" not in channel_edge
    assert channel_edge["command"] == (
        "bash scripts/deployment/local/run-console-service.sh operator-channel-edge"
    )
    assert "prepare-channel-edge-env.sh" in service_script

    assert "fdai.delivery.observation_campaign_cli" in service_script
    assert 'FDAI_OBSERVATION_DSN="$FDAI_STATE_STORE_DSN"' in service_script
    assert 'FDAI_OBSERVATION_SCOPES="$AZURE_SUBSCRIPTION_ID"' in service_script


def test_workspace_exposes_explicit_local_lifecycle_previews() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    tasks_by_label = {task["label"]: task for task in tasks["tasks"]}
    for label, module, source, port, state_argument in (
        (
            "lifecycle: serve example hub (8090)",
            "fdai_lifecycle_hub.cli",
            "hub",
            8090,
            "",
        ),
        (
            "lifecycle: serve example release hub (8091)",
            "fdai_release_hub",
            "release-hub",
            8091,
            " ${env:HOME}/.local/state/fdai/lifecycle-preview/release-hub",
        ),
    ):
        task = tasks_by_label[label]
        assert task["type"] == "shell"
        assert task["command"] == (
            f"${{workspaceFolder}}/.venv/bin/python -m {module} serve{state_argument} --port {port}"
        )
        python_paths = [
            "${workspaceFolder}/lifecycle/hub/src",
            "${workspaceFolder}/packages/deployment-cli/src",
        ]
        expected_env = {"PYTHONPATH": ":".join(python_paths)}
        if source == "hub":
            expected_env["FDAI_LIFECYCLE_HUB_DATABASE_URL"] = (
                "sqlite+pysqlite:///${env:HOME}/.local/state/fdai/lifecycle-preview/hub/hub.db"
            )
        else:
            expected_env["PYTHONPATH"] = ":".join(
                [f"${{workspaceFolder}}/lifecycle/{source}/src", *python_paths]
            )
        assert task["options"] == {"cwd": "${workspaceFolder}", "env": expected_env}
        assert task["isBackground"] is True
        assert task["runOptions"] == {"instanceLimit": 1}
        assert "dependsOn" not in task
        background = task["problemMatcher"]["background"]
        assert background["activeOnStart"] is True
        assert re.search(background["beginsPattern"], "Started server process [123]")
        readiness = background["endsPattern"]
        assert re.search(readiness, f"Uvicorn running on http://127.0.0.1:{port}")
        assert not re.search(readiness, f"Uvicorn running on http://0.0.0.0:{port}")
        assert not re.search(readiness, f"Uvicorn running on http://127.0.0.1:{port + 2}")
        assert task["presentation"]["panel"] == "dedicated"


def test_workspace_exposes_explicit_local_development_diagnostics() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    tasks_by_label = {task["label"]: task for task in tasks["tasks"]}
    start = tasks_by_label["dev discuss: start or restart profiled services"]
    assert start["command"] == (
        "bash scripts/deployment/local/restart-console-services.sh --auth-mode browser-entra"
    )
    assert start["dependsOn"] == ["console: require primary worktree"]
    assert start["runOptions"] == {
        "instanceLimit": 1,
        "instancePolicy": "terminateOldest",
    }
    assert (
        "--duration-ms 5000"
        in tasks_by_label["dev discuss: profile selected service (5s)"]["command"]
    )
    inputs = {item["id"]: item for item in tasks["inputs"]}
    assert inputs["diagnosticService"]["options"] == [
        "core-control-plane",
        "operator-service",
    ]
