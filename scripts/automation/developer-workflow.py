#!/usr/bin/env python3
"""Report bounded, read-only FDAI developer workflow diagnostics."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
UTC = timezone.utc  # noqa: UP017 - tracked hooks also support system Python 3.10.
MAX_PATHS = 20


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_diagnostic(root: Path) -> dict[str, Any]:
    top_level = _git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return {
            "reason_code": "git_repository_unavailable",
            "status": "unavailable",
        }
    repo_root = Path(top_level.stdout.strip()).resolve()
    head = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    branch = _git(repo_root, "branch", "--show-current")
    if head.returncode != 0 or branch.returncode != 0:
        return {
            "reason_code": "git_history_unavailable",
            "status": "unavailable",
            "worktree": str(repo_root),
        }
    return {
        "branch": branch.stdout.strip() or "detached",
        "head": head.stdout.strip(),
        "status": "ok",
        "worktree": str(repo_root),
    }


def _index_diagnostic(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        return {
            "reason_code": "git_index_unavailable",
            "status": "unavailable",
        }
    staged = 0
    unstaged = 0
    untracked = 0
    overlaps: list[str] = []
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        index_state, worktree_state = line[0], line[1]
        path = line[3:]
        if index_state == "?" and worktree_state == "?":
            untracked += 1
            continue
        staged += int(index_state != " ")
        unstaged += int(worktree_state != " ")
        if index_state != " " and worktree_state != " ":
            overlaps.append(path)
    return {
        "overlap_count": len(overlaps),
        "overlap_paths": overlaps[:MAX_PATHS],
        "staged_count": staged,
        "status": "warning" if overlaps else "ok",
        "unstaged_count": unstaged,
        "untracked_count": untracked,
    }


def status_report(root: Path) -> dict[str, Any]:
    """Build one versioned report without changing repository or process state."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "schema_version": SCHEMA_VERSION,
        "sections": {
            "git": _git_diagnostic(root),
            "index": _index_diagnostic(root),
        },
    }


def _render_text(report: dict[str, Any]) -> str:
    git_state = report["sections"]["git"]
    if git_state["status"] != "ok":
        return f"developer-workflow: unavailable ({git_state['reason_code']})"
    index_state = report["sections"]["index"]
    return (
        "developer-workflow: ok\n"
        f"  worktree: {git_state['worktree']}\n"
        f"  branch:   {git_state['branch']}\n"
        f"  head:     {git_state['head'][:12]}\n"
        f"  index:    {index_state['status']} "
        f"(staged={index_state['staged_count']}, unstaged={index_state['unstaged_count']}, "
        f"untracked={index_state['untracked_count']}, overlap={index_state['overlap_count']})"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report = status_report(Path.cwd())
    if arguments.as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
