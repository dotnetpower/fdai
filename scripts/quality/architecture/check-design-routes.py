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
SKILLS_ROOT = REPO_ROOT / ".github/skills"
PROMPTS_ROOT = REPO_ROOT / ".github/prompts"
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
    lines = match.group("body").splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        if not raw_line or raw_line[0].isspace() or ":" not in raw_line:
            index += 1
            continue
        key, raw_value = raw_line.split(":", 1)
        scalar = raw_value.strip()
        if scalar in {"|", "|-", ">", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (not lines[index] or lines[index][0].isspace()):
                if content := lines[index].strip():
                    block.append(content)
                index += 1
            values[key.strip()] = " ".join(block)
            continue
        values[key.strip()] = scalar.strip('"').strip("'")
        index += 1
    return values


def _content_line_count(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


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
    instruction_budget = int(manifest.get("instruction_line_budget", 0))
    skill_budget = int(manifest.get("skill_line_budget", 0))
    skill_description_budget = int(manifest.get("skill_description_char_budget", 0))
    prompt_budget = int(manifest.get("prompt_line_budget", 0))

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
        line_count = _content_line_count(path)
        if instruction_budget > 0 and line_count > instruction_budget:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {line_count} content lines exceeds budget "
                f"{instruction_budget}"
            )

    unregistered = actual_instructions - referenced_instructions
    for path in sorted(unregistered):
        errors.append(f"instruction is not referenced by any route: {path.relative_to(REPO_ROOT)}")

    skill_paths = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    if not skill_paths:
        errors.append(".github/skills must contain at least one */SKILL.md")
    for path in skill_paths:
        relative = path.relative_to(REPO_ROOT)
        try:
            metadata = _frontmatter(path)
        except ValueError as exc:
            errors.append(f"{relative}: {exc}")
            continue
        if metadata.get("name") != path.parent.name:
            errors.append(f"{relative}: name must match skill directory {path.parent.name}")
        description = metadata.get("description", "")
        if not description:
            errors.append(f"{relative}: missing description")
        elif skill_description_budget > 0 and len(description) > skill_description_budget:
            errors.append(
                f"{relative}: description has {len(description)} characters; budget is "
                f"{skill_description_budget}"
            )
        line_count = _content_line_count(path)
        if skill_budget > 0 and line_count > skill_budget:
            errors.append(f"{relative}: {line_count} content lines exceeds budget {skill_budget}")

    prompt_paths = sorted(PROMPTS_ROOT.glob("*.prompt.md"))
    if not prompt_paths:
        errors.append(".github/prompts must contain at least one *.prompt.md")
    for path in prompt_paths:
        relative = path.relative_to(REPO_ROOT)
        try:
            metadata = _frontmatter(path)
        except ValueError as exc:
            errors.append(f"{relative}: {exc}")
            continue
        if not metadata.get("description"):
            errors.append(f"{relative}: missing description")
        line_count = _content_line_count(path)
        if prompt_budget > 0 and line_count > prompt_budget:
            errors.append(f"{relative}: {line_count} content lines exceeds budget {prompt_budget}")
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
