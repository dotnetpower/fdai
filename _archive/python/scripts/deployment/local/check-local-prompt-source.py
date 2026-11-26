#!/usr/bin/env python3
"""Keep the standard local Core prompt source reproducible by default."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PROMPT_ROOT = "rule-catalog/prompts/"
_ALLOW_ENV = "FDAI_LOCAL_ALLOW_DIRTY_PROMPTS"


def dirty_prompt_paths(repo_root: Path) -> tuple[str, ...]:
    """Return tracked modifications and untracked prompt artifacts."""

    changed = _git_paths(repo_root, "diff", "--name-only", "HEAD", "--", _PROMPT_ROOT)
    untracked = _git_paths(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        _PROMPT_ROOT,
    )
    return tuple(sorted(set(changed) | set(untracked)))


def _git_paths(repo_root: Path, *args: str) -> tuple[str, ...]:
    result = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    dirty = dirty_prompt_paths(repo_root)
    if not dirty:
        return 0
    # Diagnostics go to stderr, so a caller that reads a digest from stdout still can.
    if os.environ.get(_ALLOW_ENV) == "1":
        print(
            "local prompt source is dirty; explicit worktree prompt opt-in is active: "
            + ", ".join(dirty),
            file=sys.stderr,
        )
        return 0
    print(
        "local Core start blocked: uncommitted prompt artifacts would shadow the "
        "committed prompt source: " + ", ".join(dirty),
        file=sys.stderr,
    )
    print(
        f"commit the prompt changes or set {_ALLOW_ENV}=1 for an explicit development run",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
