"""Contracts for bounded developer workflow diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "automation" / "developer-workflow.py"


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository script with test-owned arguments.
        [sys.executable, str(SCRIPT), *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed Git arguments against a temporary repository.
        ["git", *arguments],  # noqa: S607 - Git is the fixed test executable.
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_status_json_is_versioned_and_read_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    (repo / "example.txt").write_text("value\n", encoding="utf-8")
    assert _git(repo, "add", "example.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    before = _git(repo, "status", "--porcelain").stdout

    result = _run(repo, "status", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["read_only"] is True
    assert payload["sections"]["git"]["status"] == "ok"
    assert payload["sections"]["git"]["branch"] == "main"
    after = _git(repo, "status", "--porcelain").stdout
    assert after == before


def test_status_reports_non_repository_as_unavailable(tmp_path: Path) -> None:
    result = _run(tmp_path, "status", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sections"]["git"] == {
        "reason_code": "git_repository_unavailable",
        "status": "unavailable",
    }
    assert payload["sections"]["index"] == {
        "reason_code": "git_index_unavailable",
        "status": "unavailable",
    }


def test_status_reports_staged_and_unstaged_overlap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _git(repo, "config", "user.email", "user@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Example User").returncode == 0
    tracked = repo / "tracked.txt"
    tracked.write_text("initial\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    tracked.write_text("staged\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    tracked.write_text("unstaged\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    result = _run(repo, "status", "--json")

    assert result.returncode == 0, result.stderr
    index = json.loads(result.stdout)["sections"]["index"]
    assert index == {
        "overlap_count": 1,
        "overlap_paths": ["tracked.txt"],
        "staged_count": 1,
        "status": "warning",
        "unstaged_count": 1,
        "untracked_count": 1,
    }
