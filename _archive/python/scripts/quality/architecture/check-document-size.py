#!/usr/bin/env python3
"""Bound roadmap document size while legacy documents may grow during implementation.

New documents stay under their line limit. A legacy document over the growth floor may grow with
an advisory so a first implementation can land before the document is split; it is rejected only
above the hard ceiling.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NEW_DOC_MAX_LINES = 400
LEGACY_GROWTH_FLOOR = 650
LEGACY_HARD_MAX_LINES = 1500
FOCUSED_DOCUMENT_MAX_BYTES = {
    "docs/roadmap/architecture/code-map.md": 32 * 1024,
    "docs/roadmap/architecture/code-map-ko.md": 32 * 1024,
}


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


def _current_byte_count(relative: str, diff_range: str | None) -> int | None:
    if diff_range == "--cached":
        result = _run_git("show", f":{relative}", check=False)
        return len(result.stdout.encode("utf-8")) if result.returncode == 0 else None
    path = REPO_ROOT / relative
    return len(path.read_bytes()) if path.is_file() else None


def size_violations(documents: tuple[tuple[str, int, int | None], ...]) -> list[str]:
    errors: list[str] = []
    for path, current_lines, old_lines in documents:
        if old_lines is None and current_lines > NEW_DOC_MAX_LINES:
            errors.append(
                f"{path}: new document has {current_lines} lines; maximum is {NEW_DOC_MAX_LINES}"
            )
        elif (
            old_lines is not None
            and current_lines > LEGACY_HARD_MAX_LINES
            and current_lines > old_lines
        ):
            errors.append(
                f"{path}: legacy document grew {old_lines} -> {current_lines}; maximum is "
                f"{LEGACY_HARD_MAX_LINES}; split it into focused owner documents"
            )
    return errors


def size_advisories(documents: tuple[tuple[str, int, int | None], ...]) -> list[str]:
    """Report legacy growth that remains allowed until the owning feature is complete."""
    return [
        f"{path}: legacy oversized document grew {old_lines} -> {current_lines}; split it "
        "into focused owner documents after the feature's first completion"
        for path, current_lines, old_lines in documents
        if old_lines is not None
        and LEGACY_GROWTH_FLOOR < current_lines <= LEGACY_HARD_MAX_LINES
        and current_lines > old_lines
    ]


def byte_size_violations(documents: tuple[tuple[str, int], ...]) -> list[str]:
    errors: list[str] = []
    for path, current_bytes in documents:
        maximum = FOCUSED_DOCUMENT_MAX_BYTES.get(path)
        if maximum is not None and current_bytes > maximum:
            errors.append(
                f"{path}: navigation index is {current_bytes} bytes; maximum is {maximum}"
            )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) > 2 or (len(argv) == 2 and argv[1].startswith("-") and argv[1] != "--cached"):
        print("usage: check-document-size.py [--cached | <git-diff-range>]", file=sys.stderr)
        return 2
    diff_range = argv[1] if len(argv) == 2 else None
    base_ref = _base_ref(diff_range)
    documents = []
    byte_documents = []
    for relative in _changed_docs(diff_range):
        current_lines = _current_line_count(relative, diff_range)
        current_bytes = _current_byte_count(relative, diff_range)
        if current_lines is None or current_bytes is None:
            continue
        documents.append(
            (
                relative,
                current_lines,
                _old_line_count(base_ref, relative),
            )
        )
        byte_documents.append((relative, current_bytes))
    for advisory in size_advisories(tuple(documents)):
        print(f"document-size: ADVISORY: {advisory}", file=sys.stderr)
    errors = size_violations(tuple(documents))
    errors.extend(byte_size_violations(tuple(byte_documents)))
    if errors:
        for error in errors:
            print(f"document-size: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"document-size: OK ({len(documents)} changed roadmap document(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
