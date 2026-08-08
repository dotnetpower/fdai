#!/usr/bin/env python3
"""Batch committed changes through one repository-wide validation queue."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.validation_queue_runner import run_validation
from scripts.automation.validation_queue_support import (
    COMMIT_PATTERN,
    UTC,
    QueuePaths,
    atomic_write,
    git,
    initialize,
    pending_commits,
    queue_paths,
    resolve_commit,
)


def enqueue(paths: QueuePaths, revision: str) -> str:
    initialize(paths)
    commit = resolve_commit(paths, revision)
    if (paths.receipts / f"{commit}.json").is_file():
        return commit
    payload = {
        "commit": commit,
        "enqueued_at": datetime.now(UTC).isoformat(),
        "worktree": str(paths.repo_root),
    }
    atomic_write(paths.pending / f"{commit}.json", json.dumps(payload, sort_keys=True) + "\n")
    return commit


def _commits_in_range(paths: QueuePaths, revision_range: str) -> list[str]:
    output = git("rev-list", "--reverse", revision_range, cwd=paths.repo_root).stdout
    return [commit for commit in output.splitlines() if COMMIT_PATTERN.fullmatch(commit)]


def ensure_range(paths: QueuePaths, revision_range: str) -> list[str]:
    return [enqueue(paths, commit) for commit in _commits_in_range(paths, revision_range)]


def unvalidated_range(paths: QueuePaths, revision_range: str) -> list[str]:
    initialize(paths)
    return [
        commit
        for commit in _commits_in_range(paths, revision_range)
        if not (paths.receipts / f"{commit}.json").is_file()
    ]


def check_commit(paths: QueuePaths, revision: str) -> int:
    initialize(paths)
    commit = resolve_commit(paths, revision)
    if (paths.receipts / f"{commit}.json").is_file():
        print(f"validation-queue: commit is validated: {commit}")
        return 0
    print(
        f"validation-queue: BLOCKED - commit requires integration validation: {commit}",
        file=sys.stderr,
    )
    print("  Run 'make validation-run' in the dedicated integration session.", file=sys.stderr)
    return 1


def run(paths: QueuePaths, mode: str) -> int:
    return run_validation(paths, mode)


def status(paths: QueuePaths, *, show_all: bool = False) -> int:
    pending = pending_commits(paths)
    head = resolve_commit(paths, "HEAD")
    history = git("rev-list", "--reverse", "--topo-order", head, cwd=paths.repo_root).stdout
    reachable = [commit for commit in history.splitlines() if commit in pending]
    elsewhere = sorted(pending - set(reachable))
    print(
        f"validation-queue: {len(reachable)} reachable pending commit(s), "
        f"{len(elsewhere)} elsewhere"
    )
    for commit in reachable:
        print(f"  {commit}")
    if show_all:
        for commit in elsewhere:
            print(f"  {commit} (elsewhere)")
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
    check_commit_parser = subparsers.add_parser("check-commit")
    check_commit_parser.add_argument("revision", nargs="?", default="HEAD")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--all", action="store_true", dest="all_gates")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--all", action="store_true", dest="all_pending")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = queue_paths()
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
    if arguments.command == "check-commit":
        return check_commit(paths, arguments.revision)
    if arguments.command == "run":
        return run(paths, "all" if arguments.all_gates else "fast")
    return status(paths, show_all=arguments.all_pending)


if __name__ == "__main__":
    raise SystemExit(main())
