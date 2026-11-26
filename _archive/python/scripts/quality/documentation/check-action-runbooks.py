#!/usr/bin/env python3
"""Validate operator-runbook schema and shipped ActionType coverage."""

from __future__ import annotations

import argparse
import fnmatch
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "1.0.0"
REQUIRED_SECTIONS = frozenset(
    {"preconditions", "procedure", "verification", "rollback", "audit_trail"}
)


@dataclass(frozen=True, slots=True)
class RunbookBinding:
    """One schema-valid runbook and the ActionType patterns it covers."""

    path: Path
    patterns: tuple[str, ...]


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _front_matter(path: Path) -> tuple[dict[str, Any] | None, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            loaded = yaml.safe_load("\n".join(lines[1:index]))
            return (loaded if isinstance(loaded, dict) else {}), "\n".join(lines[index + 1 :])
    raise ValueError("front matter has no closing delimiter")


def _action_type_names(root: Path, errors: list[str]) -> tuple[str, ...]:
    action_types_root = root / "rule-catalog/action-types"
    names: list[str] = []
    for path in sorted(action_types_root.glob("*.yaml")):
        try:
            loaded = _load_yaml(path)
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: malformed ActionType YAML ({exc})")
            continue
        name = loaded.get("name") if isinstance(loaded, dict) else None
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path.name}: ActionType must declare a non-empty name")
            continue
        names.append(name)
    if not names:
        errors.append(f"{action_types_root}: no ActionType declarations found")
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    errors.extend(f"{name}: duplicate ActionType declaration" for name in duplicates)
    return tuple(sorted(set(names)))


def _runbook_bindings(root: Path, errors: list[str]) -> tuple[RunbookBinding, ...]:
    runbooks_root = root / "docs/runbooks"
    bindings: list[RunbookBinding] = []
    for path in sorted(runbooks_root.glob("*.md")):
        if path.name == "README.md" or path.name.endswith("-ko.md"):
            continue
        try:
            front_matter, body = _front_matter(path)
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: malformed front matter ({exc})")
            continue
        declaration = front_matter.get("fdai_runbook") if front_matter else None
        if declaration is None:
            continue
        if not isinstance(declaration, dict):
            errors.append(f"{path.name}: fdai_runbook must be a mapping")
            continue
        if str(declaration.get("schema_version")) != SCHEMA_VERSION:
            errors.append(f"{path.name}: fdai_runbook.schema_version must be {SCHEMA_VERSION}")
        patterns = declaration.get("action_type_patterns")
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(isinstance(pattern, str) and pattern.strip() for pattern in patterns)
        ):
            errors.append(f"{path.name}: action_type_patterns must be a non-empty string list")
            continue
        sections = declaration.get("sections")
        if not isinstance(sections, dict):
            errors.append(f"{path.name}: sections must be a mapping")
            continue
        missing_sections = sorted(REQUIRED_SECTIONS - sections.keys())
        if missing_sections:
            errors.append(
                f"{path.name}: sections is missing required keys: {', '.join(missing_sections)}"
            )
            continue
        invalid_section = False
        for key in sorted(REQUIRED_SECTIONS):
            heading = sections[key]
            if not isinstance(heading, str) or not heading.strip():
                errors.append(f"{path.name}: sections.{key} must name a level-2 heading")
                invalid_section = True
                continue
            if f"## {heading.strip()}" not in body.splitlines():
                errors.append(f"{path.name}: required heading '## {heading.strip()}' is missing")
                invalid_section = True
        if invalid_section:
            continue
        bindings.append(RunbookBinding(path=path, patterns=tuple(patterns)))
    return tuple(bindings)


def validate(root: Path) -> tuple[tuple[str, ...], tuple[RunbookBinding, ...], list[str]]:
    """Return the catalog, valid bindings, and every schema or coverage error."""
    errors: list[str] = []
    action_types = _action_type_names(root, errors)
    bindings = _runbook_bindings(root, errors)
    for binding in bindings:
        for pattern in binding.patterns:
            if not any(fnmatch.fnmatchcase(name, pattern) for name in action_types):
                errors.append(f"{binding.path.name}: pattern {pattern!r} matches no ActionType")
    for action_type in action_types:
        matched = sorted(
            binding.path.name
            for binding in bindings
            if any(fnmatch.fnmatchcase(action_type, pattern) for pattern in binding.patterns)
        )
        if not matched:
            errors.append(f"{action_type}: no operator runbook matches")
        elif len(matched) > 1:
            errors.append(f"{action_type}: multiple operator runbooks match: {', '.join(matched)}")
    return action_types, bindings, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check required runbook sections and ActionType coverage."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root containing rule-catalog/action-types and docs/runbooks",
    )
    args = parser.parse_args(argv)
    action_types, bindings, errors = validate(args.root.resolve())
    if errors:
        for error in errors:
            print(f"check-action-runbooks: {error}", file=sys.stderr)
        print(
            f"check-action-runbooks: FAILED with {len(errors)} issue(s).",
            file=sys.stderr,
        )
        return 1
    print(
        "check-action-runbooks: OK "
        f"({len(action_types)} ActionType(s), {len(bindings)} runbook(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
