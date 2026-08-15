"""Shared state and Git primitives for centralized validation."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
UTC = timezone.utc  # noqa: UP017 - tracked Git hooks run with the system Python 3.10.


@dataclass(frozen=True)
class QueuePaths:
    """Paths shared by validation producers and the single validator."""

    repo_root: Path
    state_root: Path
    pending: Path
    receipts: Path
    lock: Path
    runs: Path
    stage_cache: Path
    worktree: Path
    sync_state: Path
    wake_lock: Path
    wake_request: Path


def git(
    *arguments: str,
    cwd: Path,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Git with captured text output in one repository checkout."""
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        input=input_text,
    )


def queue_paths(cwd: Path | None = None) -> QueuePaths:
    """Resolve validation state under the Git common directory."""
    start = cwd or Path.cwd()
    repo_root = Path(git("rev-parse", "--show-toplevel", cwd=start).stdout.strip())
    raw_common_dir = Path(git("rev-parse", "--git-common-dir", cwd=repo_root).stdout.strip())
    common_dir = raw_common_dir if raw_common_dir.is_absolute() else repo_root / raw_common_dir
    state_root = common_dir.resolve() / "fdai-validation-queue"
    return QueuePaths(
        repo_root=repo_root,
        state_root=state_root,
        pending=state_root / "pending",
        receipts=state_root / "receipts",
        lock=state_root / "run.lock",
        runs=state_root / "runs",
        stage_cache=state_root / "stage-cache",
        worktree=state_root / "worktree",
        sync_state=state_root / "sync-state.json",
        wake_lock=state_root / "wake.lock",
        wake_request=state_root / "wake-request.txt",
    )


def initialize(paths: QueuePaths) -> None:
    """Create all queue directories required by readers and writers."""
    paths.pending.mkdir(parents=True, exist_ok=True)
    paths.receipts.mkdir(parents=True, exist_ok=True)
    paths.runs.mkdir(parents=True, exist_ok=True)
    paths.stage_cache.mkdir(parents=True, exist_ok=True)


def resolve_commit(paths: QueuePaths, revision: str) -> str:
    """Resolve and validate one commit revision."""
    commit = git(
        "rev-parse", "--verify", f"{revision}^{{commit}}", cwd=paths.repo_root
    ).stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError(f"invalid commit id returned by git: {commit}")
    return commit


def atomic_write(path: Path, content: str) -> None:
    """Replace one state file atomically within its destination directory."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_reactivated_pending(paths: QueuePaths) -> int:
    retired = paths.state_root / "retired-pending"
    if not retired.is_dir():
        return 0
    worktrees = git("worktree", "list", "--porcelain", cwd=paths.repo_root, check=False)
    if worktrees.returncode != 0:
        return 0
    checkout_heads = [
        line.removeprefix("HEAD ").strip()
        for line in worktrees.stdout.splitlines()
        if line.startswith("HEAD ") and COMMIT_PATTERN.fullmatch(line.removeprefix("HEAD ").strip())
    ]
    reachable = git(
        "rev-list",
        "--all",
        *checkout_heads,
        cwd=paths.repo_root,
        check=False,
    )
    if reachable.returncode != 0:
        return 0
    retained = {
        commit for commit in reachable.stdout.splitlines() if COMMIT_PATTERN.fullmatch(commit)
    }
    restored = 0
    for path in retired.glob("*.json"):
        if (
            path.stem not in retained
            or (paths.receipts / path.name).is_file()
            or (paths.pending / path.name).exists()
        ):
            continue
        path.replace(paths.pending / path.name)
        restored += 1
    return restored


def pending_commits(paths: QueuePaths) -> set[str]:
    """Return syntactically valid commit ids currently awaiting validation."""
    initialize(paths)
    _restore_reactivated_pending(paths)
    return {
        path.stem for path in paths.pending.glob("*.json") if COMMIT_PATTERN.fullmatch(path.stem)
    }


def validation_base(paths: QueuePaths, first_commit: str) -> str:
    """Return the parent used to select one reachable validation batch."""
    parents = git(
        "rev-list", "--parents", "-n", "1", first_commit, cwd=paths.repo_root
    ).stdout.split()
    if len(parents) > 1:
        return parents[1]
    return git(
        "hash-object", "-t", "tree", "--stdin", cwd=paths.repo_root, input_text=""
    ).stdout.strip()
