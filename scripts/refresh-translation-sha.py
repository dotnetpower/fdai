#!/usr/bin/env python3
"""Refresh translation_source_sha (and translation_revised) in every -ko.md.

For each `foo-ko.md` under root README-ko.md or docs/**/-ko.md, look up the
current `git hash-object` of `foo.md` and rewrite the front-matter accordingly.
Also updates `translation_revised` to today's ISO date.

Idempotent: files whose SHA already matches are left untouched.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
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


def process(ko_path: Path) -> tuple[bool, str]:
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
    today = _dt.date.today().isoformat()
    fm_new, changed_date = rewrite_field(fm_new, "translation_revised", today)
    if not (changed_sha or changed_date):
        return False, f"ok (unchanged): {ko_path}"
    body = text[m.end() :]
    ko_path.write_text(head + fm_new + tail + body, encoding="utf-8")
    return True, f"rewrote: {ko_path}  sha={new_sha}  revised={today}"


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "*-ko.md"], check=True, capture_output=True, text=True
    )
    files = [Path(p) for p in result.stdout.splitlines() if p]
    n_changed = 0
    for p in files:
        changed, msg = process(p)
        print(msg)
        if changed:
            n_changed += 1
    print(f"\ntotal: {n_changed}/{len(files)} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
