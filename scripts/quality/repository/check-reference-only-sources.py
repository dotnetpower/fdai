#!/usr/bin/env python3
"""Reject tracked source bodies beside reference-only snapshot manifests."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SNAPSHOT_NAME = "SNAPSHOT.json"
SOURCE_ROOT = Path("rule-catalog/sources")
REDISTRIBUTION_VALUES = frozenset({"embeddable", "reference-only"})


def _tracked_paths(root: Path, *, cached: bool) -> tuple[Path, ...]:
    arguments = ["git", "ls-files"]
    if cached:
        arguments.append("--cached")
    arguments.extend(("--", SOURCE_ROOT.as_posix()))
    result = subprocess.run(
        arguments,
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(Path(line) for line in result.stdout.splitlines() if line)


def _read_text(root: Path, path: Path, *, cached: bool) -> str:
    if not cached:
        return (root / path).read_text(encoding="utf-8")
    result = subprocess.run(
        ["git", "show", f":{path.as_posix()}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _snapshot_payload(root: Path, path: Path, *, cached: bool) -> dict[str, Any]:
    loaded = json.loads(_read_text(root, path, cached=cached))
    if not isinstance(loaded, dict):
        raise ValueError("top-level JSON must be an object")
    return loaded


def validate(root: Path, *, cached: bool) -> tuple[int, int, list[str]]:
    """Return snapshot count, source-body count, and validation errors."""
    paths = _tracked_paths(root, cached=cached)
    snapshots = tuple(path for path in paths if path.name == SNAPSHOT_NAME)
    body_count = 0
    errors: list[str] = []
    for snapshot in snapshots:
        try:
            payload = _snapshot_payload(root, snapshot, cached=cached)
        except (json.JSONDecodeError, OSError, subprocess.CalledProcessError, ValueError) as exc:
            errors.append(f"{snapshot.as_posix()}: invalid snapshot manifest ({exc})")
            continue
        redistribution = payload.get("redistribution")
        if redistribution not in REDISTRIBUTION_VALUES:
            errors.append(
                f"{snapshot.as_posix()}: redistribution must be embeddable or reference-only"
            )
            continue
        source_bodies = tuple(
            path for path in paths if path != snapshot and snapshot.parent in path.parents
        )
        body_count += len(source_bodies)
        if redistribution == "reference-only":
            errors.extend(
                f"{path.as_posix()}: reference-only snapshot contains source body"
                for path in source_bodies
            )
    return len(snapshots), body_count, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject tracked bodies in reference-only source snapshots."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--cached",
        action="store_true",
        help="read paths and snapshot manifests from the Git index",
    )
    args = parser.parse_args(argv)
    snapshots, source_bodies, errors = validate(args.root.resolve(), cached=args.cached)
    if errors:
        for error in errors:
            print(f"check-reference-only-sources: {error}", file=sys.stderr)
        print(
            f"check-reference-only-sources: FAILED with {len(errors)} issue(s).",
            file=sys.stderr,
        )
        return 1
    print(
        "check-reference-only-sources: OK "
        f"({snapshots} snapshot(s), {source_bodies} source body file(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
