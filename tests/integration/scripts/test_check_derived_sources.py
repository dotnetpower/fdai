from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/quality/localization/check-derived-sources.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled Git arguments.
        ["git", *args],  # noqa: S607 - repository test invokes Git from PATH.
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def docs_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "--quiet").returncode == 0
    assert _git(repo, "config", "user.email", "test@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Test User").returncode == 0
    source = repo / "docs/roadmap/architecture/source.md"
    guide = repo / "docs/user-guide/guide.md"
    source.parent.mkdir(parents=True)
    guide.parent.mkdir(parents=True)
    source.write_text("# Source\n", encoding="utf-8")
    source_sha = _git(repo, "hash-object", str(source)).stdout.strip()
    guide.write_text(
        "---\n"
        "derives_from:\n"
        "  - source: docs/roadmap/architecture/source.md\n"
        f"    sha: {source_sha}\n"
        "---\n"
        "# Guide\n",
        encoding="utf-8",
    )
    assert _git(repo, "add", ".").returncode == 0
    assert _git(repo, "commit", "--quiet", "-m", "initial").returncode == 0
    return repo


def test_cached_mode_checks_the_staged_source_blob(docs_repo: Path) -> None:
    source = docs_repo / "docs/roadmap/architecture/source.md"
    source.write_text("# Staged source\n", encoding="utf-8")
    assert _git(docs_repo, "add", str(source)).returncode == 0
    staged_sha = _git(docs_repo, "rev-parse", ":docs/roadmap/architecture/source.md").stdout.strip()
    source.write_text("# Unstaged source\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert f"current={staged_sha}" in result.stderr
    assert _git(docs_repo, "hash-object", str(source)).stdout.strip() not in result.stderr


def test_cached_mode_ignores_unstaged_source_changes(docs_repo: Path) -> None:
    source = docs_repo / "docs/roadmap/architecture/source.md"
    source.write_text("# Unstaged source\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed repository script.
        [sys.executable, str(SCRIPT), "--cached"],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "OK (1 doc(s) pinned" in result.stdout


def test_pre_commit_runs_cached_derived_source_check() -> None:
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = config.split("- id: check-derived-sources", 1)[1].split("- id:", 1)[0]

    assert "check-derived-sources.py --cached" in hook
    assert "pass_filenames: false" in hook
