#!/usr/bin/env python3
"""Validate implementation ledgers in changed roadmap owner documents."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[3]
SECTION_HEADING = "## Implementation status"
SUBSECTION_HEADINGS = (
    "### Implementation scope",
    "### Implementation history",
    "### Remaining work",
)
SCOPE_HEADER = ("Area", "State", "Evidence", "Notes")
HISTORY_HEADER = ("Date", "State", "Change", "Evidence", "Remaining")
ALLOWED_STATES = frozenset(
    {
        "not-started",
        "in-progress",
        "implemented",
        "validated",
        "deferred",
        "not-applicable",
    }
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TASK_PATTERN = re.compile(r"^\s*-\s+\[[ xX]\]\s+\S")
SEPARATOR_PATTERN = re.compile(r"^:?-{3,}:?$")


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _base_ref(diff_range: str | None) -> str:
    if diff_range:
        return diff_range.split("...", 1)[0].split("..", 1)[0]
    return "HEAD"


def is_exempt(relative: str) -> bool:
    """Return whether a roadmap Markdown path is not a canonical owner doc."""
    path = PurePosixPath(relative)
    name = path.name.lower()
    return (
        name.endswith("-ko.md")
        or name in {"readme.md", "index.md"}
        or relative == "docs/roadmap/architecture/fdai-constitution.md"
        or "decisions" in path.parts
    )


def _changed_docs(diff_range: str | None, *, cached: bool) -> tuple[str, ...]:
    if cached:
        args = ("diff", "--cached", "--name-only", "--diff-filter=ACMRT", "HEAD")
    else:
        args = ("diff", "--name-only", "--diff-filter=ACMRT", diff_range or "HEAD")
    paths = _run_git(*args).stdout.splitlines()
    if diff_range is None and not cached:
        paths.extend(_run_git("ls-files", "--others", "--exclude-standard").stdout.splitlines())
    return tuple(
        sorted(
            relative
            for relative in paths
            if relative.startswith("docs/roadmap/")
            and relative.endswith(".md")
            and not is_exempt(relative)
        )
    )


def _git_text(revision: str, relative: str) -> str | None:
    result = _run_git("show", f"{revision}:{relative}", check=False)
    return result.stdout if result.returncode == 0 else None


def _current_text(relative: str, *, cached: bool) -> str | None:
    if cached:
        result = _run_git("show", f":{relative}", check=False)
        return result.stdout if result.returncode == 0 else None
    path = REPO_ROOT / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _heading_indexes(lines: list[str], heading: str) -> list[int]:
    indexes: list[int] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.strip() == heading:
            indexes.append(index)
    return indexes


def _section_end(lines: list[str], start: int, heading_prefix: str) -> int:
    in_fence = False
    for index in range(start, len(lines)):
        line = lines[index]
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith(heading_prefix):
            return index
    return len(lines)


def _cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def _table_rows(
    lines: list[str], header: tuple[str, ...]
) -> tuple[list[tuple[str, ...]], str | None]:
    for index, line in enumerate(lines):
        if _cells(line) != header:
            continue
        if index + 1 >= len(lines):
            return [], f"table {header} has no separator row"
        separator = _cells(lines[index + 1])
        if (
            separator is None
            or len(separator) != len(header)
            or not all(SEPARATOR_PATTERN.fullmatch(cell) for cell in separator)
        ):
            return [], f"table {header} has an invalid separator row"
        rows: list[tuple[str, ...]] = []
        for row_line in lines[index + 2 :]:
            row = _cells(row_line)
            if row is None:
                break
            if len(row) != len(header):
                return rows, f"table {header} has a row with {len(row)} cells"
            rows.append(row)
        if not rows:
            return [], f"table {header} must contain at least one data row"
        return rows, None
    return [], f"missing table header: {' | '.join(header)}"


def _ledger_parts(
    content: str,
) -> tuple[list[str], list[str], list[str], list[str]] | None:
    lines = content.splitlines()
    section_indexes = _heading_indexes(lines, SECTION_HEADING)
    if len(section_indexes) != 1:
        return None
    section_start = section_indexes[0] + 1
    section_end = _section_end(lines, section_start, "## ")
    section = lines[section_start:section_end]
    indexes: list[int] = []
    for heading in SUBSECTION_HEADINGS:
        matches = _heading_indexes(section, heading)
        if len(matches) != 1:
            return None
        indexes.append(matches[0])
    if indexes != sorted(indexes):
        return None
    scope = section[indexes[0] + 1 : indexes[1]]
    history = section[indexes[1] + 1 : indexes[2]]
    remaining = section[indexes[2] + 1 :]
    return lines, scope, history, remaining


def _history_rows(content: str) -> list[tuple[str, ...]]:
    parts = _ledger_parts(content)
    if parts is None:
        return []
    rows, error = _table_rows(parts[2], HISTORY_HEADER)
    return rows if error is None else []


def ledger_violations(content: str, previous: str | None = None) -> list[str]:
    """Return deterministic ledger contract violations for one owner doc."""
    errors: list[str] = []
    lines = content.splitlines()
    section_count = len(_heading_indexes(lines, SECTION_HEADING))
    if section_count != 1:
        return [f"expected exactly one '{SECTION_HEADING}' section; found {section_count}"]

    parts = _ledger_parts(content)
    if parts is None:
        return ["implementation status must contain the three required H3 headings in order"]
    _, scope_lines, history_lines, remaining_lines = parts

    scope_rows, scope_error = _table_rows(scope_lines, SCOPE_HEADER)
    if scope_error:
        errors.append(scope_error)
    else:
        for index, row in enumerate(scope_rows, start=1):
            if row[1] not in ALLOWED_STATES:
                errors.append(f"scope row {index} has unsupported state '{row[1]}'")
            if not row[0] or not row[2]:
                errors.append(f"scope row {index} requires non-empty area and evidence")

    history_rows, history_error = _table_rows(history_lines, HISTORY_HEADER)
    if history_error:
        errors.append(history_error)
    else:
        for index, row in enumerate(history_rows, start=1):
            if not DATE_PATTERN.fullmatch(row[0]):
                errors.append(f"history row {index} date must use YYYY-MM-DD")
            if row[1] not in ALLOWED_STATES:
                errors.append(f"history row {index} has unsupported state '{row[1]}'")
            if any(not cell for cell in row[2:]):
                errors.append(f"history row {index} requires change, evidence, and remaining")

    task_items = [line for line in remaining_lines if TASK_PATTERN.match(line)]
    if not task_items:
        errors.append("remaining work must contain at least one Markdown task-list item")
    if any("TBD" in line.upper() for line in task_items):
        errors.append("remaining work task-list items must not use TBD")

    if previous is not None:
        previous_rows = _history_rows(previous)
        if previous_rows and history_rows[: len(previous_rows)] != previous_rows:
            errors.append("implementation history is append-only; preserve all existing rows")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) > 2 or (len(argv) == 2 and argv[1] == ""):
        print(
            "usage: check-roadmap-implementation-tracking.py [--cached | <git-diff-range>]",
            file=sys.stderr,
        )
        return 2
    argument = argv[1] if len(argv) == 2 else None
    cached = argument == "--cached"
    diff_range = None if cached else argument
    base_ref = _base_ref(diff_range)
    failures = 0
    documents = _changed_docs(diff_range, cached=cached)
    for relative in documents:
        current = _current_text(relative, cached=cached)
        if current is None:
            continue
        previous = _git_text(base_ref, relative)
        for error in ledger_violations(current, previous):
            print(f"roadmap-implementation-tracking: ERROR: {relative}: {error}", file=sys.stderr)
            failures += 1
    if failures:
        return 1
    print(f"roadmap-implementation-tracking: OK ({len(documents)} changed owner document(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
