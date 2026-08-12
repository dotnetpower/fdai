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
    assert settings["python.analysis.nodeArguments"] == ["--max-old-space-size=2048"]
    assert settings["python.analysis.nodeExecutable"] == "auto"
    assert settings["python.analysis.useLibraryCodeForTypes"] is False
    assert settings["python.analysis.userFileIndexFollowSymlinkedFolders"] is False


def test_workspace_uses_one_instruction_and_git_sync_path() -> None:
    settings = _load_jsonc(REPO_ROOT / ".vscode" / "settings.json")
    assert isinstance(settings, dict)

    assert settings["chat.contextUsage.enabled"] is True
    assert settings["chat.useNestedAgentsMdFiles"] is False
    assert settings["github.copilot.chat.summarizeAgentConversationHistory.enabled"] is True
    assert settings["github.copilot.chat.summarizeAgentConversationHistoryThreshold"] == 160000
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


def test_expensive_console_state_preparation_is_explicit() -> None:
    tasks = _load_jsonc(REPO_ROOT / ".vscode" / "tasks.json")
    assert isinstance(tasks, dict)
    tasks_by_label = {task["label"]: task for task in tasks["tasks"]}

    prepare_state = tasks_by_label["console: prepare local state"]
    assert "runOn" not in prepare_state["runOptions"]
    assert prepare_state["runOptions"]["instanceLimit"] == 1
    assert (
        "console: prepare local state" in tasks_by_label["console: prepare full stack"]["dependsOn"]
    )
