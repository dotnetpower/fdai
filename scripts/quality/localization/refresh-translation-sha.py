#!/usr/bin/env python3
"""Refresh translation_source_sha (and translation_revised) in -ko.md files.

For each `foo-ko.md`, look up the current `git hash-object` of the sibling
`foo.md` and rewrite the front-matter accordingly. Also updates
`translation_revised` to today's ISO date **only when the SHA actually
changed**, so re-running on an already-in-sync tree is a true no-op (per
the "idempotent" contract).

Scope selection:

- No arguments -> process every tracked `*-ko.md`.
- One or more paths as arguments -> process only those files.

The path-based scoping matters because a full sweep touches ~60 files at
once, which is almost never what a per-doc translation update wants; it
was also the historical bug that motivated adding the CLI parameter.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

FM_RE = re.compile(r"\A(---\r?\n)(.*?)(\r?\n---\r?\n)", re.DOTALL)


def git_hash(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def rewrite_field(fm: str, key: str, value: str) -> tuple[str, bool]:
    """Set `key: value` in a YAML front-matter block. Return (new_fm, changed)."""
    pat = re.compile(rf"^({re.escape(key)}\s*:\s*)(.*)$", re.MULTILINE)
    new_line = f"{key}: {value}"
    m = pat.search(fm)
    if m is None:
        # Append at end.
        new_fm = fm.rstrip("\n") + "\n" + new_line
        return new_fm, True
    if m.group(2).strip() == value:
        return fm, False
    new_fm = pat.sub(f"\\g<1>{value}", fm, count=1)
    return new_fm, True


def process(ko_path: Path, *, today: str | None = None) -> tuple[bool, str]:
    """Refresh one -ko.md's translation_source_sha + translation_revised.

    ``today`` is injectable for tests; production leaves it None and reads
    ``date.today()``. Returns ``(changed, message)``.
    """
    src_path = Path(str(ko_path).replace("-ko.md", ".md"))
    if not src_path.is_file():
        return False, f"skip (no source): {ko_path}"
    text = ko_path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if m is None:
        return False, f"skip (no front-matter): {ko_path}"
    head, fm, tail = m.group(1), m.group(2), m.group(3)
    new_sha = git_hash(src_path)
    fm_new, changed_sha = rewrite_field(fm, "translation_source_sha", new_sha)
    # Only bump translation_revised when the SHA actually moved. Otherwise a
    # re-run on an in-sync tree would touch every file's date and defeat the
    # idempotency the docstring promises (and the pre-push gate depends on).
    if not changed_sha:
        return False, f"ok (unchanged): {ko_path}"
    stamp = today or _dt.date.today().isoformat()
    fm_new, _ = rewrite_field(fm_new, "translation_revised", stamp)
    body = text[m.end() :]
    ko_path.write_text(head + fm_new + tail + body, encoding="utf-8")
    return True, f"rewrote: {ko_path}  sha={new_sha}  revised={stamp}"


def _resolve_files(argv: list[str]) -> list[Path]:
    if argv:
        # Explicit scope: only the paths the caller named. A path that is not
        # a -ko.md is a user error and we fail loud rather than silently no-op.
        bad = [p for p in argv if not p.endswith("-ko.md")]
        if bad:
            raise SystemExit(
                f"refresh-translation-sha: only *-ko.md paths are valid arguments; rejected: {bad}"
            )
        return [Path(p) for p in argv]
    result = subprocess.run(
        ["git", "ls-files", "*-ko.md"], check=True, capture_output=True, text=True
    )
    return [Path(p) for p in result.stdout.splitlines() if p]


def _run(files: Iterable[Path]) -> int:
    n_changed = 0
    n_total = 0
    for p in files:
        n_total += 1
        changed, msg = process(p)
        print(msg)
        if changed:
            n_changed += 1
    print(f"\ntotal: {n_changed}/{n_total} file(s) updated.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refresh-translation-sha",
        description=(
            "Refresh translation_source_sha and translation_revised in one or "
            "more -ko.md front-matters. With no arguments, scope defaults to "
            "every tracked *-ko.md (matches the historical whole-tree behaviour); "
            "with paths, scope is exactly those files."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional -ko.md paths to scope the refresh to (default: all).",
    )
    args = parser.parse_args(argv)
    files = _resolve_files(args.paths)
    return _run(files)


if __name__ == "__main__":
    sys.exit(main())
