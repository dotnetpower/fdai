#!/usr/bin/env bash
#
# check-doc-links.sh - guard against broken markdown link targets.
#
# Every tracked ``*.md`` link that points at a relative filesystem path
# is resolved (following symlinks - mirrors the site build's
# remarkRewriteLinks plugin which resolves against the canonical
# source location, not the symlink location). A missing target is a
# broken link and fails the gate.
#
# What is NOT checked:
#   - Absolute URLs (http, https, mailto, etc.).
#   - Anchor-only targets (#section).
#   - Targets that resolve outside the repo root.
#   - Fragment (#anchor) validity - only the file part is verified.
#   - Targets that are git-ignored (e.g. ``docs/internals/`` and
#     ``examples/`` are intentionally local-only, so a tracked doc may
#     reference them without the file ever being committed). Checking
#     filesystem existence alone diverges between a developer's working
#     tree (where the untracked file is present) and CI (a clean checkout
#     where it is not); consulting ``git check-ignore`` makes the gate
#     give the same verdict in both places.
#
# Rationale (tracker #14 follow-up): the G-1..G-7 refactors moved 20+
# Python source files whose paths were baked into markdown link
# targets. 41 links pointed at non-existent files after the moves;
# without a gate, that class of drift silently accumulates. This
# script catches it at CI time.
#
# Exit codes: 0 on clean, 1 on any broken link.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

python3 - <<'PY'
import re
import subprocess
import sys
from pathlib import Path

repo = Path(".").resolve()
tracked = subprocess.check_output(
    ["git", "ls-files", "*.md"], text=True
).splitlines()

link_re = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
broken: list[tuple[str, str]] = []
scanned = 0


def is_git_ignored(path: Path) -> bool:
    """Return True if ``path`` is excluded by a .gitignore rule.

    ``git check-ignore`` answers against the ignore rules regardless of
    whether the file exists on disk, so it gives an identical verdict in
    a developer working tree and in a clean CI checkout.
    """
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(rel)],
        cwd=repo,
    )
    return result.returncode == 0


for md in tracked:
    path = repo / md
    if not path.is_file():
        continue
    # Resolve symlinks to canonical source (matches the site
    # remarkRewriteLinks plugin at site/src/plugins/rewrite-links.mjs).
    canonical = path.resolve()
    canonical_dir = canonical.parent
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    scanned += 1
    for _label, target in link_re.findall(text):
        raw = target.split()[0]
        # Skip absolute URLs, anchors, schemes.
        if raw.startswith(("http", "mailto:", "#", "//")):
            continue
        first_segment = raw.split("#", 1)[0]
        if ":" in first_segment:
            continue
        rel = first_segment.split("?", 1)[0]
        if not rel:
            continue
        target_p = (canonical_dir / rel).resolve()
        if not target_p.exists() and not is_git_ignored(target_p):
            broken.append((md, rel))

if broken:
    print(f"check-doc-links: {len(broken)} broken link(s) found:",
          file=sys.stderr)
    for md, rel in broken:
        print(f"  {md} -> {rel}", file=sys.stderr)
    sys.exit(1)

print(f"check-doc-links: OK ({scanned} tracked *.md file(s) scanned, 0 broken)")
PY
