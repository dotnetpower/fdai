from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/quality/repository/check-root-layout.py"


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled Git arguments.
        ["git", *arguments],  # noqa: S607 - test invokes Git from PATH.
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def root_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet").returncode == 0
    allowlist = repo / "scripts/lib/root-file-allowlist.txt"
    allowlist.parent.mkdir(parents=True)
    allowlist.write_text("README.md\npyproject.toml\n", encoding="utf-8")
    (repo / "README.md").write_text("# Example\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert _git(repo, "add", ".").returncode == 0
    return repo


def _run(repo: Path, *, cached: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--root", str(repo)]
    if cached:
        command.append("--cached")
    return subprocess.run(  # noqa: S603 - fixed checker with a test-owned root.
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_root_layout_accepts_allowlisted_entry_points(root_repo: Path) -> None:
    result = _run(root_repo)

    assert result.returncode == 0, result.stderr
    assert "OK (2 root files)" in result.stdout


def test_root_layout_rejects_unexpected_tracked_file(root_repo: Path) -> None:
    (root_repo / "working-notes.md").write_text("# Notes\n", encoding="utf-8")
    assert _git(root_repo, "add", "working-notes.md").returncode == 0

    result = _run(root_repo)

    assert result.returncode == 1
    assert "unexpected root file: working-notes.md" in result.stderr


def test_root_layout_rejects_untracked_root_file(root_repo: Path) -> None:
    (root_repo / "psql-output").write_text("query output\n", encoding="utf-8")

    result = _run(root_repo)
    cached = _run(root_repo, cached=True)

    assert result.returncode == 1
    assert "unexpected root file: psql-output" in result.stderr
    assert cached.returncode == 1
    assert "unexpected root file: psql-output" in cached.stderr


def test_root_layout_accepts_ignored_local_root_file(root_repo: Path) -> None:
    exclude = root_repo / ".git/info/exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("local-output\n", encoding="utf-8")
    (root_repo / "local-output").write_text("local data\n", encoding="utf-8")

    result = _run(root_repo)

    assert result.returncode == 0, result.stderr


def test_root_layout_rejects_stale_allowlist_entry(root_repo: Path) -> None:
    assert _git(root_repo, "rm", "--cached", "-f", "pyproject.toml").returncode == 0

    result = _run(root_repo)

    assert result.returncode == 1
    assert "stale allowlist entry: pyproject.toml" in result.stderr


def test_cached_root_layout_checks_staged_files_missing_from_worktree(root_repo: Path) -> None:
    note = root_repo / "working-notes.md"
    note.write_text("# Notes\n", encoding="utf-8")
    assert _git(root_repo, "add", "working-notes.md").returncode == 0
    note.unlink()

    working_tree = _run(root_repo)
    cached = _run(root_repo, cached=True)

    assert working_tree.returncode == 0, working_tree.stderr
    assert cached.returncode == 1
    assert "unexpected root file: working-notes.md" in cached.stderr


def test_root_layout_is_wired_into_ci_and_local_gates() -> None:
    command = "scripts/quality/repository/check-root-layout.py"
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    verification = (REPO_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    pre_commit = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    root_hook = pre_commit.split("- id: check-root-layout", maxsplit=1)[1].split(
        "- id:", maxsplit=1
    )[0]

    assert f"python3 {command}" in workflow
    assert f'run_gate "root-layout" python3 {command}' in verification
    assert f"python3 {command} --cached" in root_hook
    assert "always_run: true" in root_hook
