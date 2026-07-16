#!/usr/bin/env python3
"""Refresh derives_from[].sha pins in user-facing docs.

Counterpart of ``scripts/refresh-translation-sha.py``. Where that tool
re-pins ``foo-ko.md`` to ``foo.md``, this tool re-pins a user-facing doc
to the roadmap reference doc(s) it was authored from.

For each doc that declares a ``derives_from`` block in its YAML
front-matter::

    derives_from:
      - source: docs/roadmap/architecture/goals-and-metrics.md
        sha: <recorded>

each recorded ``sha`` is rewritten to the current ``git hash-object`` of
its ``source``. Run this only after reviewing the user-facing doc against
the updated roadmap source; refreshing the pin without reviewing defeats
the drift signal that ``scripts/check-derived-sources.py`` provides.

Scope selection:

- No arguments -> process every tracked doc that declares ``derives_from``.
- One or more paths as arguments -> process only those files.

The rewrite is line-based so YAML comments, ordering, and unrelated
front-matter fields are preserved. Re-running on an in-sync tree is a
no-op.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SOURCE_RE = re.compile(r"^(?P<indent>\s*)-?\s*source:\s*(?P<val>\S.*?)\s*$")
SHA_RE = re.compile(r"^(?P<prefix>\s*sha:\s*)(?P<val>\S+)\s*$")


def repo_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    return Path(out)


def git_hash(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def front_matter_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return (open_idx, close_idx) of the YAML front-matter delimiters."""
    if not lines or lines[0].strip() != "---":
        return None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return 0, idx
    return None


def process(root: Path, doc: Path) -> tuple[bool, str]:
    try:
        rel = doc.resolve().relative_to(root).as_posix()
    except ValueError:
        rel = str(doc)
    text = doc.read_text(encoding="utf-8")
    lines = text.split("\n")
    bounds = front_matter_bounds(lines)
    if bounds is None:
        return False, f"skip (no front-matter): {rel}"
    _, close_idx = bounds

    changed = False
    current_source: str | None = None
    for i in range(1, close_idx):
        line = lines[i]
        m_src = SOURCE_RE.match(line)
        if m_src:
            current_source = m_src.group("val").strip().strip("\"'")
            continue
        m_sha = SHA_RE.match(line)
        if m_sha and current_source is not None:
            source_path = root / current_source
            if not source_path.is_file():
                current_source = None
                continue
            new_sha = git_hash(source_path)
            if m_sha.group("val") != new_sha:
                lines[i] = f"{m_sha.group('prefix')}{new_sha}"
                changed = True
            current_source = None

    if not changed:
        return False, f"ok (unchanged): {rel}"
    doc.write_text("\n".join(lines), encoding="utf-8")
    return True, f"rewrote: {rel}"


def declares_derives_from(doc: Path) -> bool:
    text = doc.read_text(encoding="utf-8")
    lines = text.split("\n")
    bounds = front_matter_bounds(lines)
    if bounds is None:
        return False
    _, close_idx = bounds
    return any(line.strip().startswith("derives_from:") for line in lines[1:close_idx])


def resolve_files(root: Path, argv: list[str]) -> list[Path]:
    if argv:
        bad = [p for p in argv if not p.endswith(".md")]
        if bad:
            raise SystemExit(
                f"refresh-derived-sha: only *.md paths are valid arguments; rejected: {bad}"
            )
        return [p if (p := Path(a)).is_absolute() else root / a for a in argv]
    result = subprocess.run(
        ["git", "ls-files", "docs/**/*.md", "README.md"],
        check=True,
        capture_output=True,
        text=True,
        cwd=root,
    )
    tracked = [root / p for p in result.stdout.splitlines() if p]
    return [p for p in tracked if not p.name.endswith("-ko.md") and declares_derives_from(p)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refresh-derived-sha",
        description=(
            "Refresh derives_from[].sha pins in user-facing docs to the "
            "current git hash-object of each roadmap source. With no "
            "arguments, scope defaults to every tracked doc that declares "
            "derives_from; with paths, scope is exactly those files."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional doc paths to scope the refresh to (default: all).",
    )
    args = parser.parse_args(argv)
    root = repo_root()
    files = resolve_files(root, args.paths)

    n_changed = 0
    for doc in files:
        changed, msg = process(root, doc)
        print(msg)
        if changed:
            n_changed += 1
    print(f"\ntotal: {n_changed}/{len(files)} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
