#!/usr/bin/env python3
"""Validate the machine-readable instruction and design-document routes."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "scripts/lib/design-routes.json"
INSTRUCTIONS_ROOT = REPO_ROOT / ".github/instructions"
FRONTMATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


def _tracked_paths() -> tuple[str, ...]:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(
        sorted(
            {
                line
                for output in (tracked.stdout, untracked.stdout)
                for line in output.splitlines()
                if line
            }
        )
    )


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _frontmatter(path: Path) -> dict[str, str]:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("missing YAML frontmatter")
    values: dict[str, str] = {}
    for raw_line in match.group("body").splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        values[key.strip()] = raw_value.strip().strip('"')
    return values


def _matches(pattern: str, paths: tuple[str, ...]) -> bool:
    if pattern == "**":
        return bool(paths)
    return any(fnmatch.fnmatchcase(path, pattern) for path in paths)


def validate() -> list[str]:
    errors: list[str] = []
    manifest = _load_manifest()
    routes = manifest.get("routes")
    if manifest.get("version") != 1 or not isinstance(routes, list) or not routes:
        return ["design-routes.json must declare version 1 and a non-empty routes list"]

    tracked = _tracked_paths()
    route_ids: set[str] = set()
    referenced_instructions: set[Path] = set()
    budget = int(manifest.get("instruction_line_budget", 0))

    for route in routes:
        route_id = str(route.get("id", "")).strip()
        if not route_id:
            errors.append("route without id")
            continue
        if route_id in route_ids:
            errors.append(f"duplicate route id: {route_id}")
        route_ids.add(route_id)

        patterns = route.get("paths")
        if not isinstance(patterns, list) or not patterns:
            errors.append(f"{route_id}: paths must be a non-empty list")
        else:
            for pattern in patterns:
                if not isinstance(pattern, str) or not pattern:
                    errors.append(f"{route_id}: invalid empty path pattern")
                elif not _matches(pattern, tracked):
                    errors.append(f"{route_id}: path pattern matches no tracked file: {pattern}")
        optional_patterns = route.get("optional_paths", [])
        if not isinstance(optional_patterns, list):
            errors.append(f"{route_id}: optional_paths must be a list")
        elif any(not isinstance(pattern, str) or not pattern for pattern in optional_patterns):
            errors.append(f"{route_id}: invalid empty optional path pattern")

        must_read = route.get("must_read")
        if not isinstance(must_read, list) or not must_read:
            errors.append(f"{route_id}: must_read must be a non-empty list")
            continue
        for relative in must_read:
            path = REPO_ROOT / str(relative)
            if not path.is_file():
                errors.append(f"{route_id}: required context file does not exist: {relative}")
            if path.parent == INSTRUCTIONS_ROOT:
                referenced_instructions.add(path)

        for field in ("docs_update",):
            for relative in route.get(field, []):
                if not (REPO_ROOT / str(relative)).is_file():
                    errors.append(f"{route_id}: {field} file does not exist: {relative}")

    actual_instructions = set(INSTRUCTIONS_ROOT.glob("*.instructions.md"))
    for path in sorted(actual_instructions):
        try:
            metadata = _frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
            continue
        if not metadata.get("description"):
            errors.append(f"{path.relative_to(REPO_ROOT)}: missing description")
        if not metadata.get("applyTo"):
            errors.append(f"{path.relative_to(REPO_ROOT)}: missing applyTo")
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if budget > 0 and line_count > budget:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {line_count} lines exceeds budget {budget}"
            )

    unregistered = actual_instructions - referenced_instructions
    for path in sorted(unregistered):
        errors.append(f"instruction is not referenced by any route: {path.relative_to(REPO_ROOT)}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"design-routes: ERROR: {error}", file=sys.stderr)
        return 1
    print("design-routes: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
