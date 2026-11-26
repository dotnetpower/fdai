from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PREFLIGHT = _REPO_ROOT / "scripts" / "quality" / "ci" / "local-preflight.sh"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603, S607 - isolated local Git repositories only
        ["git", *args],  # noqa: S607 - executable is fixed
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_local_preflight_fetches_the_remote_tracking_base(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    _git(tmp_path, "init", "--initial-branch=main", str(seed))
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.com")
    (seed / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(seed, "add", "tracked.txt")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "--quiet", "origin", "main")
    _git(tmp_path, "clone", "--quiet", str(remote), str(repo))
    _git(repo, "checkout", "--quiet", "-b", "topic")
    initial_base = _git(repo, "rev-parse", "origin/main")

    (seed / "tracked.txt").write_text("updated\n", encoding="utf-8")
    _git(seed, "commit", "-am", "advance base")
    _git(seed, "push", "--quiet", "origin", "main")
    latest_base = _git(seed, "rev-parse", "HEAD")
    assert initial_base != latest_base

    venv_python = repo / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    venv_python.chmod(0o755)
    preflight = repo / "scripts" / "quality" / "ci" / "local-preflight.sh"
    preflight.parent.mkdir(parents=True)
    shutil.copyfile(_PREFLIGHT, preflight)

    result = subprocess.run(  # noqa: S603, S607 - runs the task-owned script in a temp repo
        ["bash", str(preflight), "--base", "origin/main"],  # noqa: S607 - executable is fixed
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "HEAD is 1 commit(s) behind origin/main" in result.stderr
    assert _git(repo, "rev-parse", "origin/main") == latest_base
