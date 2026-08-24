from __future__ import annotations

import json
from pathlib import Path

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


def test_workspace_exposes_explicit_complete_console_topology() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    tasks_by_label = {task["label"]: task for task in tasks["tasks"]}
    assert len(tasks_by_label) == 15

    prepare_stack = tasks_by_label["console: prepare full stack"]
    assert prepare_stack["command"] == (
        "bash scripts/deployment/local/prepare-console-full-stack.sh"
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
    preparation_positions = [
        preparation_script.index(f"run_stage \\\n  {stage} \\\n") for stage in preparation_stages
    ]
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
        "instanceLimit": 1,
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
        "dev-access: configure VPN on folder open",
    }

    dev_access = tasks_by_label["dev-access: configure VPN on folder open"]
    assert dev_access["presentation"]["close"] is True
    assert dev_access["presentation"]["revealProblems"] == "onProblem"

    visible_tasks = {task["label"] for task in tasks["tasks"] if not task.get("hide", False)}
    assert visible_tasks == {
        "git: pull now (rebase, autostash)",
        "console: Playwright quick (desktop)",
        "design mocks: serve (5373)",
        "console: prepare full stack",
        "console: start core runtime",
        "console: restart core runtime",
        "console: start full stack",
        "console: keep full stack ready (10m)",
        "console: wait full stack ready",
        "channel edge: Operator Slack and Teams (Local)",
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
        "endsPattern": "service=core-runtime event=ready$",
    }

    restart_core_runtime = tasks_by_label["console: restart core runtime"]
    assert restart_core_runtime["command"] == core_runtime["command"]
    assert restart_core_runtime["isBackground"] is True
    assert restart_core_runtime["runOptions"] == {
        "instanceLimit": 1,
        "instancePolicy": "silent",
    }
    assert restart_core_runtime["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=core-runtime event=starting$",
        "endsPattern": "service=core-runtime event=ready$",
    }

    local_services = tasks_by_label["console: start local services"]
    assert local_services["command"] == ("bash scripts/deployment/local/start-console-services.sh")
    assert local_services["isBackground"] is True
    assert "dependsOn" not in local_services
    assert local_services["runOptions"] == {
        "instanceLimit": 1,
        "instancePolicy": "silent",
    }
    assert local_services["problemMatcher"]["background"] == {
        "activeOnStart": True,
        "beginsPattern": "service=console-stack event=starting$",
        "endsPattern": "service=console-stack event=started$",
    }

    wait_ready = tasks_by_label["console: wait full stack ready"]
    assert wait_ready["command"].endswith("developer-workflow.py local-services --wait-seconds 60")
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
        "inventory-reconciliation",
        "observation-campaign",
        "console-frontend",
    )
    for service_name in managed_services:
        assert f"  {service_name}\n" in supervisor_script
    assert "run-console-service.sh" in supervisor_script
    assert "developer-workflow.py" in supervisor_script
    assert "local-services" in supervisor_script
    assert supervisor_script.index("event=started") < supervisor_script.index("--wait-seconds 60")
    assert "--wait-seconds 60" in supervisor_script
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
    assert "--only core-runtime" in service_script
    assert service_script.index("--only core-runtime") < service_script.index(
        "service=core-runtime event=ready"
    )
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
