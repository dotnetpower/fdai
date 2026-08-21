#!/usr/bin/env python3
"""Ratchet oversized roadmap documents toward focused owner documents."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NEW_DOC_MAX_LINES = 400
LEGACY_GROWTH_FLOOR = 650


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _base_ref(diff_range: str | None) -> str:
    if diff_range and diff_range != "--cached":
        return diff_range.split("...", 1)[0].split("..", 1)[0]
    return "HEAD"


def _diff_arguments(diff_range: str | None) -> tuple[str, ...]:
    arguments = ["diff"]
    if diff_range == "--cached":
        arguments.append("--cached")
    arguments.extend(("--name-only", "--diff-filter=ACMRT"))
    if diff_range != "--cached":
        arguments.append(diff_range or "HEAD")
    return tuple(arguments)


def _changed_docs(diff_range: str | None) -> tuple[str, ...]:
    paths = _run_git(*_diff_arguments(diff_range)).stdout.splitlines()
    if diff_range is None:
        paths.extend(_run_git("ls-files", "--others", "--exclude-standard").stdout.splitlines())
    return tuple(
        sorted(path for path in paths if path.startswith("docs/roadmap/") and path.endswith(".md"))
    )


def _old_line_count(base_ref: str, relative: str) -> int | None:
    result = _run_git("show", f"{base_ref}:{relative}", check=False)
    if result.returncode != 0:
        return None
    return len(result.stdout.splitlines())


def _current_line_count(relative: str, diff_range: str | None) -> int | None:
    if diff_range == "--cached":
        result = _run_git("show", f":{relative}", check=False)
        return len(result.stdout.splitlines()) if result.returncode == 0 else None
    path = REPO_ROOT / relative
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else None


def size_violations(documents: tuple[tuple[str, int, int | None], ...]) -> list[str]:
    errors: list[str] = []
    for path, current_lines, old_lines in documents:
        if old_lines is None and current_lines > NEW_DOC_MAX_LINES:
            errors.append(
                f"{path}: new document has {current_lines} lines; maximum is {NEW_DOC_MAX_LINES}"
            )
        elif (
            old_lines is not None
            and current_lines > LEGACY_GROWTH_FLOOR
            and current_lines > old_lines
        ):
            errors.append(
                f"{path}: legacy oversized document grew {old_lines} -> {current_lines}; "
                "split it into focused owner documents"
            )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) > 2 or (len(argv) == 2 and argv[1].startswith("-") and argv[1] != "--cached"):
        print("usage: check-document-size.py [--cached | <git-diff-range>]", file=sys.stderr)
        return 2
    diff_range = argv[1] if len(argv) == 2 else None
    base_ref = _base_ref(diff_range)
    documents = []
    for relative in _changed_docs(diff_range):
        current_lines = _current_line_count(relative, diff_range)
        if current_lines is None:
            continue
        documents.append(
            (
                relative,
                current_lines,
                _old_line_count(base_ref, relative),
            )
        )
    errors = size_violations(tuple(documents))
    if errors:
        for error in errors:
            print(f"document-size: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"document-size: OK ({len(documents)} changed roadmap document(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
