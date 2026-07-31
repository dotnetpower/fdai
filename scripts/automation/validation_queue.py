#!/usr/bin/env python3
"""Batch committed changes through one repository-wide validation queue."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
UTC = timezone.utc  # noqa: UP017 - tracked Git hooks run with the system Python 3.10.


@dataclass(frozen=True)
class QueuePaths:
    repo_root: Path
    state_root: Path
    pending: Path
    receipts: Path
    lock: Path


def _git(
    *arguments: str,
    cwd: Path,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        input=input_text,
    )


def _queue_paths(cwd: Path | None = None) -> QueuePaths:
    start = cwd or Path.cwd()
    repo_root = Path(_git("rev-parse", "--show-toplevel", cwd=start).stdout.strip())
    raw_common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo_root).stdout.strip())
    common_dir = raw_common_dir if raw_common_dir.is_absolute() else repo_root / raw_common_dir
    state_root = common_dir.resolve() / "fdai-validation-queue"
    return QueuePaths(
        repo_root=repo_root,
        state_root=state_root,
        pending=state_root / "pending",
        receipts=state_root / "receipts",
        lock=state_root / "run.lock",
    )


def _initialize(paths: QueuePaths) -> None:
    paths.pending.mkdir(parents=True, exist_ok=True)
    paths.receipts.mkdir(parents=True, exist_ok=True)


def _resolve_commit(paths: QueuePaths, revision: str) -> str:
    commit = _git(
        "rev-parse", "--verify", f"{revision}^{{commit}}", cwd=paths.repo_root
    ).stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError(f"invalid commit id returned by git: {commit}")
    return commit


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def enqueue(paths: QueuePaths, revision: str) -> str:
    _initialize(paths)
    commit = _resolve_commit(paths, revision)
    if (paths.receipts / f"{commit}.json").is_file():
        return commit
    payload = {
        "commit": commit,
        "enqueued_at": datetime.now(UTC).isoformat(),
        "worktree": str(paths.repo_root),
    }
    _atomic_write(paths.pending / f"{commit}.json", json.dumps(payload, sort_keys=True) + "\n")
    return commit


def _commits_in_range(paths: QueuePaths, revision_range: str) -> list[str]:
    output = _git("rev-list", "--reverse", revision_range, cwd=paths.repo_root).stdout
    return [commit for commit in output.splitlines() if COMMIT_PATTERN.fullmatch(commit)]


def ensure_range(paths: QueuePaths, revision_range: str) -> list[str]:
    return [enqueue(paths, commit) for commit in _commits_in_range(paths, revision_range)]


def unvalidated_range(paths: QueuePaths, revision_range: str) -> list[str]:
    _initialize(paths)
    return [
        commit
        for commit in _commits_in_range(paths, revision_range)
        if not (paths.receipts / f"{commit}.json").is_file()
    ]


def _pending_commits(paths: QueuePaths) -> set[str]:
    _initialize(paths)
    return {
        path.stem for path in paths.pending.glob("*.json") if COMMIT_PATTERN.fullmatch(path.stem)
    }


def _validation_base(paths: QueuePaths, first_commit: str) -> str:
    parents = _git(
        "rev-list", "--parents", "-n", "1", first_commit, cwd=paths.repo_root
    ).stdout.split()
    if len(parents) > 1:
        return parents[1]
    return _git(
        "hash-object",
        "-t",
        "tree",
        "--stdin",
        cwd=paths.repo_root,
        input_text="",
    ).stdout.strip()


def _link_cache(source: Path, destination: Path) -> None:
    if source.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source, target_is_directory=True)


def _run_command(arguments: list[str], *, cwd: Path, env: dict[str, str]) -> int:
    completed = subprocess.run(arguments, cwd=cwd, env=env, check=False)
    return completed.returncode


def _validation_environment(paths: QueuePaths) -> dict[str, str]:
    cache_root = paths.state_root / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.setdefault("FDAI_PYTEST_MAX_WORKERS", "2")
    environment.setdefault("MYPY_CACHE_DIR", str(cache_root / "mypy"))
    environment.setdefault("RUFF_CACHE_DIR", str(cache_root / "ruff"))
    environment["FDAI_VALIDATION_ACTIVE"] = "1"
    return environment


def _record_receipts(
    paths: QueuePaths,
    commits: list[str],
    *,
    base: str,
    head: str,
    mode: str,
) -> None:
    validated_at = datetime.now(UTC).isoformat()
    for commit in commits:
        payload = {
            "commit": commit,
            "validated_at": validated_at,
            "validated_base": base,
            "validated_head": head,
            "mode": mode,
        }
        _atomic_write(
            paths.receipts / f"{commit}.json",
            json.dumps(payload, sort_keys=True) + "\n",
        )
        (paths.pending / f"{commit}.json").unlink(missing_ok=True)


def _run_locked(paths: QueuePaths, mode: str) -> int:
    head = _resolve_commit(paths, "HEAD")
    pending = _pending_commits(paths)
    history = _git("rev-list", "--reverse", "--topo-order", head, cwd=paths.repo_root).stdout
    selected = [commit for commit in history.splitlines() if commit in pending]
    if not selected:
        print("validation-queue: no pending commits reachable from HEAD")
        return 0

    base = _validation_base(paths, selected[0])
    revision_range = f"{base}..{head}"
    temporary_parent = Path(tempfile.mkdtemp(prefix="fdai-validation-"))
    validation_root = temporary_parent / "worktree"
    added = False
    try:
        _git(
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(validation_root),
            head,
            cwd=paths.repo_root,
        )
        added = True
        _link_cache(paths.repo_root / ".venv", validation_root / ".venv")
        _link_cache(
            paths.repo_root / "console" / "node_modules",
            validation_root / "console" / "node_modules",
        )
        environment = _validation_environment(paths)
        print(
            f"validation-queue: validating {len(selected)} commit(s) at {head[:12]} "
            f"with mode={mode}"
        )
        if mode == "fast":
            changed_status = _run_command(
                ["bash", "scripts/automation/tests-for-diff.sh", "--run", revision_range],
                cwd=validation_root,
                env=environment,
            )
            if changed_status != 0:
                return changed_status
            verify_arguments = ["bash", "scripts/verify.sh", "--fast"]
        else:
            verify_arguments = ["bash", "scripts/verify.sh", "--all"]
        verify_status = _run_command(verify_arguments, cwd=validation_root, env=environment)
        if verify_status != 0:
            return verify_status
        _record_receipts(paths, selected, base=base, head=head, mode=mode)
        print(f"validation-queue: validated {len(selected)} commit(s)")
        return 0
    finally:
        if added:
            _git(
                "worktree",
                "remove",
                "--force",
                str(validation_root),
                cwd=paths.repo_root,
                check=False,
            )
        shutil.rmtree(temporary_parent, ignore_errors=True)


def run(paths: QueuePaths, mode: str) -> int:
    _initialize(paths)
    with paths.lock.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("validation-queue: another integration validator is active", file=sys.stderr)
            return 3
        return _run_locked(paths, mode)


def status(paths: QueuePaths) -> int:
    pending = sorted(_pending_commits(paths))
    print(f"validation-queue: {len(pending)} pending commit(s)")
    for commit in pending:
        print(f"  {commit}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    enqueue_parser = subparsers.add_parser("enqueue")
    enqueue_parser.add_argument("revision", nargs="?", default="HEAD")
    ensure_parser = subparsers.add_parser("ensure-range")
    ensure_parser.add_argument("revision_range")
    check_parser = subparsers.add_parser("check-range")
    check_parser.add_argument("revision_range")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--all", action="store_true", dest="all_gates")
    subparsers.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = _queue_paths()
    if arguments.command == "enqueue":
        commit = enqueue(paths, arguments.revision)
        print(f"validation-queue: enqueued {commit}")
        return 0
    if arguments.command == "ensure-range":
        commits = ensure_range(paths, arguments.revision_range)
        print(f"validation-queue: ensured {len(commits)} commit(s)")
        return 0
    if arguments.command == "check-range":
        missing = unvalidated_range(paths, arguments.revision_range)
        if not missing:
            print("validation-queue: outgoing range is validated")
            return 0
        print(
            "validation-queue: BLOCKED - commits require integration validation:", file=sys.stderr
        )
        for commit in missing:
            print(f"  {commit}", file=sys.stderr)
        print("  Run 'make validation-run' in the dedicated integration session.", file=sys.stderr)
        return 1
    if arguments.command == "run":
        return run(paths, "all" if arguments.all_gates else "fast")
    return status(paths)


if __name__ == "__main__":
    raise SystemExit(main())
