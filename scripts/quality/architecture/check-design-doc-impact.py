#!/usr/bin/env python3
"""Require route-owned design documentation in behavior-changing diffs."""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "scripts/lib/design-routes.json"


def _git_paths(args: list[str]) -> set[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in completed.stdout.splitlines() if line}


def changed_paths(diff_range: str | None = None, *, cached: bool = False) -> set[str]:
    if cached:
        return _git_paths(["--cached", "HEAD"])
    if diff_range:
        return _git_paths([diff_range])
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return (
        _git_paths(["HEAD"])
        | _git_paths(["--cached", "HEAD"])
        | {line for line in untracked.stdout.splitlines() if line}
    )


def _matches(path: str, pattern: str) -> bool:
    return pattern == "**" or fnmatch.fnmatchcase(path, pattern)


def missing_doc_updates(
    paths: set[str], manifest: dict[str, Any]
) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    failures: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for route in manifest["routes"]:
        required_docs = tuple(str(path) for path in route.get("docs_update", ()))
        if not required_docs:
            continue
        patterns = tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        impacted = tuple(
            sorted(path for path in paths if any(_matches(path, pattern) for pattern in patterns))
        )
        if not impacted or any(doc in paths for doc in required_docs):
            continue
        failures.append((str(route["id"]), impacted, required_docs))
    return failures


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(
            "usage: check-design-doc-impact.py [--cached | <git-diff-range>]",
            file=sys.stderr,
        )
        return 2
    argument = argv[1] if len(argv) == 2 else None
    paths = changed_paths(
        argument if argument != "--cached" else None,
        cached=argument == "--cached",
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    failures = missing_doc_updates(paths, manifest)
    if failures:
        for route_id, impacted, required_docs in failures:
            print(f"design-doc-impact: ERROR: route {route_id} changed:", file=sys.stderr)
            for path in impacted:
                print(f"  code: {path}", file=sys.stderr)
            print("  update at least one owning design doc:", file=sys.stderr)
            for path in required_docs:
                print(f"  doc:  {path}", file=sys.stderr)
        return 1
    print(f"design-doc-impact: OK ({len(paths)} changed path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
