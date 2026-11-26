#!/usr/bin/env python3
"""Keep repository-root files limited to stable entry points."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_ALLOWLIST = Path("scripts/lib/root-file-allowlist.txt")


def _tracked_root_files(root: Path, *, cached: bool) -> frozenset[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    root_paths = frozenset(path for path in result.stdout.split("\0") if path and "/" not in path)
    if cached:
        return root_paths
    return frozenset(
        path for path in root_paths if (root / path).exists() or (root / path).is_symlink()
    )


def _untracked_root_files(root: Path) -> frozenset[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(path for path in result.stdout.split("\0") if path and "/" not in path)


def _allowed_root_files(path: Path) -> frozenset[str]:
    return frozenset(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def validate(
    root: Path, allowlist: Path, *, cached: bool = False
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return unexpected non-ignored files and stale allowlist entries."""
    tracked = _tracked_root_files(root, cached=cached)
    present = tracked | _untracked_root_files(root)
    allowed = _allowed_root_files(allowlist)
    return tuple(sorted(present - allowed)), tuple(sorted(allowed - tracked))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject tracked repository-root files outside the approved entry points."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help="allowlist path relative to the repository root",
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="validate the staged Git index instead of the working tree",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    allowlist = args.allowlist if args.allowlist.is_absolute() else root / args.allowlist
    unexpected, missing = validate(root, allowlist, cached=args.cached)
    if unexpected or missing:
        for path in unexpected:
            print(f"check-root-layout: unexpected root file: {path}", file=sys.stderr)
        for path in missing:
            print(f"check-root-layout: stale allowlist entry: {path}", file=sys.stderr)
        print(
            "check-root-layout: move internal artifacts under their owning directory or update "
            "the allowlist for a reviewed stable entry point.",
            file=sys.stderr,
        )
        return 1
    print(f"check-root-layout: OK ({len(_allowed_root_files(allowlist))} root files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
