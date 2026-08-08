#!/usr/bin/env python3
"""Report or remove clean completed worktrees conservatively."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    """One registered Git worktree."""

    path: Path
    head: str


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=check,
    )


def _worktrees(root: Path) -> list[Worktree]:
    output = _git(root, "worktree", "list", "--porcelain").stdout
    entries: list[Worktree] = []
    path: Path | None = None
    head: str | None = None
    for line in [*output.splitlines(), ""]:
        if not line:
            if path is not None and head is not None:
                entries.append(Worktree(path.resolve(), head))
            path = None
            head = None
        elif line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line.startswith("HEAD "):
            head = line.removeprefix("HEAD ")
    return entries


def _has_active_process(path: Path) -> bool:
    proc = Path("/proc")
    if not proc.is_dir():
        return True
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            cwd = (process / "cwd").resolve(strict=True)
        except OSError:
            continue
        if cwd == path or cwd.is_relative_to(path):
            return True
    return False


def _latest_activity(root: Path, worktree: Worktree) -> float:
    path_mtime = worktree.path.stat().st_mtime
    commit_time = _git(root, "show", "-s", "--format=%ct", worktree.head).stdout.strip()
    try:
        return max(path_mtime, float(commit_time))
    except ValueError:
        return path_mtime


def _classification(
    root: Path,
    worktree: Worktree,
    *,
    primary: Path,
    validation_worktree: Path,
    main_ref: str,
    minimum_activity: float,
) -> str:
    if worktree.path in {primary, validation_worktree}:
        return "protected"
    if not worktree.path.is_dir():
        return "missing"
    if _git(worktree.path, "status", "--porcelain", "--untracked-files=all").stdout:
        return "dirty"
    if _git(root, "merge-base", "--is-ancestor", worktree.head, main_ref, check=False).returncode:
        return "unmerged"
    if _latest_activity(root, worktree) > minimum_activity:
        return "recent"
    if _has_active_process(worktree.path):
        return "active"
    return "candidate"


def _retire_receipted_pending(root: Path, removed_path: Path) -> int:
    raw_common = Path(_git(root, "rev-parse", "--git-common-dir").stdout.strip())
    common = raw_common if raw_common.is_absolute() else root / raw_common
    state = common.resolve() / "fdai-validation-queue"
    pending = state / "pending"
    receipts = state / "receipts"
    retired = state / "retired" / "pending"
    count = 0
    for path in pending.glob("*.json"):
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("worktree") != str(removed_path):
            continue
        if not (receipts / path.name).is_file():
            continue
        retired.mkdir(parents=True, exist_ok=True)
        path.replace(retired / path.name)
        count += 1
    return count


def maintain(
    root: Path,
    *,
    apply: bool,
    main_ref: str,
    min_age_hours: float,
) -> int:
    """Report candidates and optionally remove only proven completed worktrees."""
    primary = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    raw_common = Path(_git(root, "rev-parse", "--git-common-dir").stdout.strip())
    common = raw_common if raw_common.is_absolute() else primary / raw_common
    validation_worktree = common.resolve() / "fdai-validation-queue" / "worktree"
    minimum_activity = time.time() - min_age_hours * 3600
    removed = 0
    retired = 0
    counts: dict[str, int] = {}
    for worktree in _worktrees(primary):
        category = _classification(
            primary,
            worktree,
            primary=primary,
            validation_worktree=validation_worktree,
            main_ref=main_ref,
            minimum_activity=minimum_activity,
        )
        counts[category] = counts.get(category, 0) + 1
        print(f"{category} {worktree.path}")
        if category != "candidate" or not apply:
            continue
        completed = _git(
            primary,
            "worktree",
            "remove",
            str(worktree.path),
            check=False,
        )
        if completed.returncode != 0:
            print(
                f"worktree-maintenance: failed to remove {worktree.path}: "
                f"{completed.stderr.strip()}",
                file=sys.stderr,
            )
            return completed.returncode
        removed += 1
        retired += _retire_receipted_pending(primary, worktree.path)
    print(
        "worktree-maintenance: "
        + " ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        + f" removed={removed} retired_pending={retired} apply={str(apply).lower()}"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--main-ref", default="main")
    parser.add_argument("--min-age-hours", type=float, default=24.0)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.min_age_hours < 0:
        print("worktree-maintenance: --min-age-hours must be non-negative", file=sys.stderr)
        return 2
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
    return maintain(
        root,
        apply=arguments.apply,
        main_ref=arguments.main_ref,
        min_age_hours=arguments.min_age_hours,
    )


if __name__ == "__main__":
    raise SystemExit(main())
