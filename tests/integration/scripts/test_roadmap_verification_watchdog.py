from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

AUTOMATION = Path(__file__).resolve().parents[2] / "scripts" / "automation"


def _load(name: str, filename: str) -> ModuleType:
    sys.path.insert(0, str(AUTOMATION))
    path = AUTOMATION / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(executable: str, cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled executable, arguments, and repository
        [executable, *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_active_session_lease_holds_watchdog(tmp_path: Path) -> None:
    module = _load("fdai_roadmap_watchdog", "roadmap_verification_watchdog.py")
    lease = tmp_path / ".improve/sessions/editor.lease"
    lease.parent.mkdir(parents=True)
    lease.touch()

    assert module._active_session_leases(tmp_path, 900) == ["editor"]
    old = time.time() - 901
    os.utime(lease, (old, old))
    assert module._active_session_leases(tmp_path, 900) == []


def test_recent_copilot_activity_holds_watchdog(tmp_path: Path, monkeypatch) -> None:
    module = _load("fdai_roadmap_watchdog_activity", "roadmap_verification_watchdog.py")
    storage = tmp_path / "workspaceStorage"
    log = storage / "workspace/GitHub.copilot-chat/debug-logs/session/main.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("FDAI_VSCODE_WORKSPACE_STORAGE", str(storage))

    assert module._recent_copilot_activity(900) == ["main"]


def test_timer_is_persistent_and_apply_is_explicit(tmp_path: Path) -> None:
    module = _load(
        "fdai_roadmap_timer",
        "install_roadmap_verification_timer.py",
    )

    report_service, timer = module._unit_text(tmp_path.resolve(), apply=False)
    apply_service, _ = module._unit_text(tmp_path.resolve(), apply=True)

    assert "roadmap_verification_watchdog.py" in report_service
    assert " --apply" not in report_service
    assert " --apply --integrate" in apply_service
    assert "OnUnitInactiveSec=20min" in timer
    assert "Persistent=true" in timer
    assert "TimeoutStartSec=2h" in report_service


def test_timer_installer_creates_dedicated_campaign_worktree(tmp_path: Path) -> None:
    module = _load(
        "fdai_roadmap_timer_campaign",
        "install_roadmap_verification_timer.py",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(module._GIT, repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(module._GIT, repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(module._GIT, repo, "config", "user.name", "Example User").returncode == 0
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    assert _git(module._GIT, repo, "add", "tracked.txt").returncode == 0
    assert _git(module._GIT, repo, "commit", "--quiet", "-m", "initial").returncode == 0
    (repo / ".venv").mkdir()
    (repo / ".improve/sessions").mkdir(parents=True)
    campaign = tmp_path / "campaign"

    created = module._prepare_campaign_worktree(
        repo,
        campaign,
        "roadmap-verification/campaign",
    )

    assert created == campaign
    assert (campaign / ".venv").is_symlink()
    assert (campaign / ".improve").is_symlink()
    branch = _git(module._GIT, campaign, "branch", "--show-current").stdout.strip()
    assert branch == "roadmap-verification/campaign"
    assert (
        module._prepare_campaign_worktree(
            repo,
            campaign,
            "roadmap-verification/campaign",
        )
        == campaign
    )


def test_make_and_scripts_readme_expose_the_pipeline_facade() -> None:
    root = AUTOMATION.parents[2]
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    readme = (root / "scripts/README.md").read_text(encoding="utf-8")

    assert "roadmap-verification-sync:" in makefile
    assert "roadmap-verification-status:" in makefile
    assert "roadmap_verification_worker.py --apply --integrate" in makefile
    assert ".git/fdai-roadmap-verification/" in readme
    assert "install_roadmap_verification_timer.py install --apply" in readme
    assert "lease expires and the next tick reclaims that same document" in readme


def test_entrypoints_load_with_system_python() -> None:
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file():
        pytest.skip("system Python is unavailable")

    for filename in (
        "roadmap_verification_cli.py",
        "roadmap_verification_worker.py",
        "roadmap_verification_watchdog.py",
        "install_roadmap_verification_timer.py",
    ):
        result = subprocess.run(  # noqa: S603 - fixed system Python and repository script
            [str(system_python), str(AUTOMATION / filename), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
