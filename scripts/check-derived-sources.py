#!/usr/bin/env python3
"""check-derived-sources - keep user-facing docs in sync with their roadmap sources.

FDAI keeps two kinds of Markdown with different natures:

- ``docs/roadmap/**`` are *development reference* docs - the engineering
  source of truth for the design.
- ``docs/user-guide/**`` (and the root ``README.md``) are *user-facing*
  docs - authored for readers, published to the docs site.

A user-facing doc may be *authored from* one or more roadmap docs (for
example, a Get Started page that summarizes tier coverage figures defined
in ``docs/roadmap/architecture/goals-and-metrics.md``). That derivation is
a copy, and copies drift silently when the source changes.

This gate makes the derivation explicit and enforceable. A user-facing doc
opts in by declaring, in its YAML front-matter::

    derives_from:
      - source: docs/roadmap/architecture/goals-and-metrics.md
        sha: <git hash-object of that file at authoring time>

The gate recomputes ``git hash-object`` of every declared source and fails
when a recorded ``sha`` no longer matches. A mismatch means the roadmap
source moved and the user-facing doc must be reviewed and, once updated,
re-pinned with ``scripts/refresh-derived-sha.py``.

Only docs that declare ``derives_from`` are checked, so the gate is
opt-in and never burdens docs that do not reference the roadmap.

Design mirror: this is the roadmap-source counterpart of
``check-translations.sh`` (which pins ``foo-ko.md`` to ``foo.md`` via
``translation_source_sha``). Here we pin a user-facing doc to its roadmap
source(s) via ``derives_from[].sha``.

Exit codes: 0 on success, 1 on any drift or malformed declaration.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

FRONT_MATTER_DELIM = "---"


def repo_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    return Path(out)


def git_hash(path: Path) -> str | None:
    """Return `git hash-object <path>`, or None when the file is absent."""
    if not path.is_file():
        return None
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def read_front_matter(path: Path) -> dict | None:
    """Parse the YAML front-matter block of a Markdown file.

    Returns the parsed mapping, or None when the file has no front-matter.
    Raises yaml.YAMLError on malformed YAML (surfaced by the caller as a
    reportable error rather than a crash).
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FRONT_MATTER_DELIM):
        return None
    lines = text.splitlines()
    # First line is the opening delimiter; find the closing one.
    for idx in range(1, len(lines)):
        if lines[idx].strip() == FRONT_MATTER_DELIM:
            block = "\n".join(lines[1:idx])
            parsed = yaml.safe_load(block)
            return parsed if isinstance(parsed, dict) else {}
    return None


def enumerate_docs(root: Path) -> list[Path]:
    """All in-scope English canonical Markdown files (excludes -ko.md)."""
    candidates: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        candidates.append(readme)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        candidates.extend(docs_dir.rglob("*.md"))
    return [p for p in candidates if not p.name.endswith("-ko.md")]


def check_doc(root: Path, doc: Path) -> list[str]:
    """Validate one doc's derives_from block. Returns a list of error strings."""
    rel = doc.relative_to(root).as_posix()
    try:
        fm = read_front_matter(doc)
    except yaml.YAMLError as exc:
        return [f"{rel}: malformed YAML front-matter ({exc})"]
    if not fm or "derives_from" not in fm:
        return []

    declarations = fm["derives_from"]
    if not isinstance(declarations, list):
        return [
            f"{rel}: 'derives_from' must be a list of {{source, sha}} entries, "
            f"got {type(declarations).__name__}"
        ]

    errors: list[str] = []
    for i, entry in enumerate(declarations):
        where = f"{rel}: derives_from[{i}]"
        if not isinstance(entry, dict) or "source" not in entry or "sha" not in entry:
            errors.append(f"{where}: each entry needs 'source' and 'sha' keys")
            continue
        source = str(entry["source"])
        recorded = str(entry["sha"])
        source_path = root / source
        if not source.startswith("docs/roadmap/"):
            errors.append(
                f"{where}: source '{source}' must be a roadmap reference doc under docs/roadmap/"
            )
            continue
        current = git_hash(source_path)
        if current is None:
            errors.append(f"{where}: source '{source}' does not exist")
            continue
        if recorded != current:
            errors.append(
                f"{where}: stale. '{source}' changed "
                f"(recorded={recorded}, current={current}). Review this "
                f"user-facing doc against the updated roadmap source, then run "
                f"`python3 scripts/refresh-derived-sha.py {rel}`."
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    root = repo_root()
    docs = enumerate_docs(root)
    all_errors: list[str] = []
    checked = 0
    for doc in sorted(docs):
        errors = check_doc(root, doc)
        if errors:
            all_errors.extend(errors)
        # Count only docs that actually declared a derivation.
        try:
            fm = read_front_matter(doc)
        except yaml.YAMLError:
            fm = None
        if fm and "derives_from" in fm:
            checked += 1

    for err in all_errors:
        print(f"check-derived-sources: {err}", file=sys.stderr)

    if all_errors:
        print(
            f"check-derived-sources: FAILED with {len(all_errors)} issue(s).",
            file=sys.stderr,
        )
        return 1

    print(f"check-derived-sources: OK ({checked} doc(s) pinned to roadmap sources).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
