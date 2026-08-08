"""Contracts for conservative completed-worktree cleanup."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "automation" / "worktree-maintenance.py"


def _run(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed test commands and temporary paths
        list(arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _commit(repo: Path, message: str, content: str) -> str:
    (repo / "value.txt").write_text(content, encoding="utf-8")
    assert _run(repo, "git", "add", "value.txt").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", message).returncode == 0
    return _run(repo, "git", "rev-parse", "HEAD").stdout.strip()


def test_cleanup_removes_only_clean_merged_inactive_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run(repo, "git", "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _run(repo, "git", "config", "user.email", "user@example.com").returncode == 0
    assert _run(repo, "git", "config", "user.name", "Example User").returncode == 0
    _commit(repo, "initial", "initial\n")

    completed = tmp_path / "completed"
    dirty = tmp_path / "dirty"
    assert (
        _run(repo, "git", "worktree", "add", "-q", "-b", "completed", str(completed)).returncode
        == 0
    )
    completed_head = _commit(completed, "completed", "completed\n")
    assert _run(repo, "git", "merge", "--ff-only", "completed").returncode == 0
    assert (
        _run(repo, "git", "worktree", "add", "-q", "-b", "dirty", str(dirty), "HEAD").returncode
        == 0
    )
    (dirty / "dirty.txt").write_text("keep\n", encoding="utf-8")

    common = Path(_run(repo, "git", "rev-parse", "--git-common-dir").stdout.strip())
    state = repo / common / "fdai-validation-queue"
    (state / "pending").mkdir(parents=True)
    (state / "receipts").mkdir()
    (state / "pending" / f"{completed_head}.json").write_text(
        json.dumps({"commit": completed_head, "worktree": str(completed)}) + "\n",
        encoding="utf-8",
    )
    (state / "receipts" / f"{completed_head}.json").write_text("{}\n", encoding="utf-8")

    preview = _run(repo, "python3", str(SCRIPT), "--min-age-hours", "0")
    applied = _run(repo, "python3", str(SCRIPT), "--min-age-hours", "0", "--apply")

    assert preview.returncode == 0, preview.stderr
    assert f"candidate {completed}" in preview.stdout
    assert f"dirty {dirty}" in preview.stdout
    assert applied.returncode == 0, applied.stderr
    assert not completed.exists()
    assert dirty.exists()
    assert (state / "retired" / "pending" / f"{completed_head}.json").is_file()
    assert not (state / "pending" / f"{completed_head}.json").exists()
    shutil.rmtree(dirty)


def test_makefile_exposes_preview_and_apply_targets() -> None:
    makefile = (Path(__file__).resolve().parents[3] / "Makefile").read_text(encoding="utf-8")

    assert "worktree-maintenance:" in makefile
    assert "worktree-cleanup:" in makefile
    assert "worktree-maintenance.py" in makefile
