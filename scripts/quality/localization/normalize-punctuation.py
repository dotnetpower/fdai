#!/usr/bin/env python3
"""Normalize Unicode typography to plain ASCII across markdown files.

Enforces the coding-conventions rule:
    Prefer plain ASCII punctuation (-, ", ') over smart quotes and em-dashes.

Replacements (in prose only, never inside code fences or inline `code`):
    U+2014 EM DASH        (--) -> -
    U+2013 EN DASH        (--) -> -
    U+2026 HORIZONTAL ELLIPSIS -> ...
    U+201C LEFT DOUBLE QUOTATION MARK  -> "
    U+201D RIGHT DOUBLE QUOTATION MARK -> "
    U+2018 LEFT SINGLE QUOTATION MARK  -> '
    U+2019 RIGHT SINGLE QUOTATION MARK -> '
    U+00A0 NO-BREAK SPACE  -> ' '

Scope: markdown files passed on the command line, or all tracked *.md files
if no arguments are given.

Skip regions:
  * Fenced code blocks (``` or ~~~).
  * Inline code spans (`...`).

Frontmatter is normalized too (rare case, but a smart-quoted title is still
a defect). The check-translations gate will re-sync -ko.md SHAs after this
script runs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPLACEMENTS = {
    "\u2014": "-",  # em-dash
    "\u2013": "-",  # en-dash
    "\u2026": "...",  # ellipsis
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u00a0": " ",
}

# Precompile the replacement table for str.translate.
TRANSLATE_TABLE = str.maketrans({k: v for k, v in REPLACEMENTS.items()})

INLINE_CODE_RE = re.compile(r"`+[^`\n]*?`+")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)")


def normalize_prose(segment: str) -> str:
    return segment.translate(TRANSLATE_TABLE)


def process_line(line: str) -> str:
    """Rewrite non-code portions of a line."""
    out = []
    last = 0
    for m in INLINE_CODE_RE.finditer(line):
        out.append(normalize_prose(line[last : m.start()]))
        out.append(line[m.start() : m.end()])  # keep code span verbatim
        last = m.end()
    out.append(normalize_prose(line[last:]))
    return "".join(out)


def process_text(text: str) -> str:
    lines = text.split("\n")
    out = []
    in_fence = False
    fence_char = ""
    for line in lines:
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)[0]  # ` or ~
            if not in_fence:
                in_fence = True
                fence_char = marker
            elif marker == fence_char:
                in_fence = False
                fence_char = ""
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        out.append(process_line(line))
    return "\n".join(out)


def collect_targets(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    # Default: every git-tracked *.md file.
    result = subprocess.run(["git", "ls-files", "*.md"], check=True, capture_output=True, text=True)
    return [Path(p) for p in result.stdout.splitlines() if p]


def count_targets(text: str) -> dict[str, int]:
    return {ch: text.count(ch) for ch in REPLACEMENTS if text.count(ch) > 0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", help="Files (default: all tracked *.md).")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Do not write. Exit 1 if any file would change.",
    )
    ap.add_argument(
        "--whole-file",
        action="store_true",
        help=(
            "Do not skip code fences or inline code. Applies a straight "
            "str.translate over the entire file. Use for non-markdown source "
            "files (.py/.yaml/.json/.ts/...) where the whole file is code."
        ),
    )
    args = ap.parse_args()

    targets = collect_targets(args.paths)
    changed: list[tuple[Path, dict[str, int]]] = []
    for path in targets:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        if args.whole_file:
            rewritten = original.translate(TRANSLATE_TABLE)
        else:
            rewritten = process_text(original)
        if rewritten != original:
            # Report the delta (prose only) for accurate reporting.
            delta = {}
            for ch in REPLACEMENTS:
                orig_c = original.count(ch)
                new_c = rewritten.count(ch)
                if orig_c != new_c:
                    delta[ch] = orig_c - new_c
            changed.append((path, delta))
            if not args.check:
                path.write_text(rewritten, encoding="utf-8")

    if args.check:
        if changed:
            for path, delta in changed:
                summary = ", ".join(f"{repr(ch)}:-{n}" for ch, n in delta.items())
                print(f"WOULD MODIFY {path}  ({summary})")
            print(f"\ncheck failed: {len(changed)} file(s) contain non-ASCII typography.")
            return 1
        print("check ok: no non-ASCII typography in prose.")
        return 0

    if not changed:
        print("no changes.")
        return 0
    for path, delta in changed:
        summary = ", ".join(f"{repr(ch)}:-{n}" for ch, n in delta.items())
        print(f"rewrote {path}  ({summary})")
    print(f"\ntotal: {len(changed)} file(s) rewritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
