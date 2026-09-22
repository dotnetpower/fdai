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
re-pinned with ``scripts/quality/localization/refresh-derived-sha.py``.

Only docs that declare ``derives_from`` are checked, so the gate is
opt-in and never burdens docs that do not reference the roadmap.

Design mirror: this is the roadmap-source counterpart of
``check-translations.sh`` (which pins ``foo-ko.md`` to ``foo.md`` via
``translation_source_sha``). Here we pin a user-facing doc to its roadmap
source(s) via ``derives_from[].sha``.

The same pass validates every ``sources[].blob_sha`` in the packaged System
Knowledge catalog. This makes cited roadmap and implementation-source changes
fail before a stale catalog reaches a later regression shard.

Exit codes: 0 on success, 1 on any drift or malformed declaration.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

FRONT_MATTER_DELIM = "---"
SYSTEM_KNOWLEDGE_CATALOG = Path(
    "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json"
)
PROTECTED_MAIN_REFS = ("refs/remotes/origin/main", "refs/heads/main")
DERIVED_SOURCE_TOOL_PATHS = frozenset(
    {
        ".pre-commit-config.yaml",
        "scripts/quality/localization/check-derived-sources.py",
        "scripts/quality/localization/refresh-derived-sha.py",
        SYSTEM_KNOWLEDGE_CATALOG.as_posix(),
    }
)


def repo_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    return Path(out)


def git_hash(root: Path, path: Path, *, cached: bool) -> str | None:
    """Return the worktree or index blob hash, or None when the file is absent."""
    if cached:
        rel = path.relative_to(root).as_posix()
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f":{rel}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    if not path.is_file():
        return None
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def git_commit(root: Path, ref: str) -> str | None:
    """Resolve one Git ref to a commit, or return None when unavailable."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    """Return whether Git proves ``ancestor`` precedes ``descendant``."""
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def protected_main_revision(root: Path) -> str | None:
    """Resolve the local protected-main tracking ref when history is available."""
    for ref in PROTECTED_MAIN_REFS:
        revision = git_commit(root, ref)
        if revision is not None:
            return revision
    return None


def read_repo_text(root: Path, path: Path, *, cached: bool) -> str | None:
    """Read one worktree or staged repository file."""
    if cached:
        rel = path.relative_to(root).as_posix()
        result = subprocess.run(
            ["git", "show", f":{rel}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout if result.returncode == 0 else None
    return path.read_text(encoding="utf-8") if path.is_file() else None


def read_front_matter(root: Path, path: Path, *, cached: bool) -> dict[str, object] | None:
    """Parse the YAML front-matter block of a Markdown file.

    Returns the parsed mapping, or None when the file has no front-matter.
    Raises yaml.YAMLError on malformed YAML (surfaced by the caller as a
    reportable error rather than a crash).
    """
    text = read_repo_text(root, path, cached=cached)
    if text is None:
        return None
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


def enumerate_docs(root: Path, *, cached: bool) -> list[Path]:
    """All in-scope English canonical Markdown files (excludes -ko.md)."""
    if cached:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--", "README.md", "docs"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return [
            root / rel
            for rel in result.stdout.splitlines()
            if rel.endswith(".md") and not rel.endswith("-ko.md")
        ]
    candidates: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        candidates.append(readme)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        candidates.extend(docs_dir.rglob("*.md"))
    return [p for p in candidates if not p.name.endswith("-ko.md")]


def staged_paths(root: Path) -> frozenset[str]:
    """Return paths whose staged snapshot may affect a derived-source result."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(result.stdout.splitlines())


def system_knowledge_source_paths(root: Path, *, cached: bool) -> frozenset[str] | None:
    """Read the catalog source set, or force a full check when it is malformed."""
    text = read_repo_text(root, root / SYSTEM_KNOWLEDGE_CATALOG, cached=cached)
    if text is None:
        return frozenset()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return None
    paths: set[str] = set()
    for record in records:
        sources = record.get("sources") if isinstance(record, dict) else None
        if not isinstance(sources, list):
            return None
        for source in sources:
            path = source.get("path") if isinstance(source, dict) else None
            if not isinstance(path, str):
                return None
            paths.add(path)
    return frozenset(paths)


def staged_inputs_require_check(root: Path) -> bool:
    """Select the full cached check from staged owning inputs only."""
    changed = staged_paths(root)
    if not changed:
        return False
    if changed & DERIVED_SOURCE_TOOL_PATHS:
        return True
    if any(path == "README.md" or path.startswith("docs/") for path in changed):
        return True
    catalog_sources = system_knowledge_source_paths(root, cached=True)
    return catalog_sources is None or bool(changed & catalog_sources)


def check_doc(root: Path, doc: Path, *, cached: bool) -> list[str]:
    """Validate one doc's derives_from block. Returns a list of error strings."""
    rel = doc.relative_to(root).as_posix()
    try:
        fm = read_front_matter(root, doc, cached=cached)
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
        current = git_hash(root, source_path, cached=cached)
        if current is None:
            errors.append(f"{where}: source '{source}' does not exist")
            continue
        if recorded != current:
            errors.append(
                f"{where}: stale. '{source}' changed "
                f"(recorded={recorded}, current={current}). Review this "
                f"user-facing doc against the updated roadmap source, then run "
                f"`python3 scripts/quality/localization/refresh-derived-sha.py {rel}`."
            )
    return errors


def check_system_knowledge_catalog(
    root: Path,
    *,
    cached: bool,
) -> tuple[list[str], int]:
    """Validate every source blob pinned by the packaged System Knowledge catalog."""
    catalog_path = root / SYSTEM_KNOWLEDGE_CATALOG
    text = read_repo_text(root, catalog_path, cached=cached)
    if text is None:
        return [], 0
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"{SYSTEM_KNOWLEDGE_CATALOG}: malformed JSON ({exc})"], 0
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return [f"{SYSTEM_KNOWLEDGE_CATALOG}: 'records' must be a list"], 0

    errors: list[str] = []
    source_revision = payload.get("source_revision")
    if not isinstance(source_revision, str) or len(source_revision) != 40:
        errors.append(f"{SYSTEM_KNOWLEDGE_CATALOG}: source_revision must be a full Git commit SHA")
    else:
        shallow = (
            subprocess.check_output(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=root,
                text=True,
            ).strip()
            == "true"
        )
        protected_revision = protected_main_revision(root)
        if not shallow and protected_revision is None:
            errors.append(f"{SYSTEM_KNOWLEDGE_CATALOG}: protected main ref is unavailable")
        elif (
            not shallow
            and protected_revision is not None
            and not git_is_ancestor(root, source_revision, protected_revision)
        ):
            errors.append(
                f"{SYSTEM_KNOWLEDGE_CATALOG}: source_revision {source_revision} "
                "is not an ancestor of protected main"
            )
    pinned: dict[str, str] = {}
    for record_index, record in enumerate(records):
        sources = record.get("sources") if isinstance(record, dict) else None
        if not isinstance(sources, list):
            errors.append(
                f"{SYSTEM_KNOWLEDGE_CATALOG}: records[{record_index}].sources must be a list"
            )
            continue
        for source_index, source in enumerate(sources):
            where = f"{SYSTEM_KNOWLEDGE_CATALOG}: records[{record_index}].sources[{source_index}]"
            if not isinstance(source, dict):
                errors.append(f"{where} must be an object")
                continue
            source_value = source.get("path")
            recorded_value = source.get("blob_sha")
            if not isinstance(source_value, str) or not isinstance(recorded_value, str):
                errors.append(f"{where} needs string 'path' and 'blob_sha' values")
                continue
            source_path = Path(source_value)
            if source_path.is_absolute() or ".." in source_path.parts:
                errors.append(f"{where} path must stay repository-relative")
                continue
            prior = pinned.setdefault(source_value, recorded_value)
            if prior != recorded_value:
                errors.append(
                    f"{SYSTEM_KNOWLEDGE_CATALOG}: source '{source_value}' has conflicting blob SHAs"
                )
                continue

    for source, recorded in sorted(pinned.items()):
        current = git_hash(root, root / source, cached=cached)
        if current is None:
            errors.append(f"{SYSTEM_KNOWLEDGE_CATALOG}: source '{source}' does not exist")
        elif current != recorded:
            errors.append(
                f"{SYSTEM_KNOWLEDGE_CATALOG}: stale System Knowledge catalog source "
                f"'{source}' (recorded={recorded}, current={current}). Regenerate with "
                "`uv run --package fdai-system-knowledge-service "
                "fdai-system-knowledge-build-catalog --repo-root . "
                "--protected-main-ref refs/remotes/origin/main --output "
                "services/system-knowledge-service/src/"
                "fdai_system_knowledge_service/data/catalog.json`."
            )
    return errors, len(pinned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check user-facing documentation pins to roadmap source blobs."
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Read documents and source hashes from the Git index.",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Skip the cached check when no staged owning input changed.",
    )
    args = parser.parse_args(argv)
    root = repo_root()
    if args.changed_only and not args.cached:
        parser.error("--changed-only requires --cached")
    if args.changed_only and not staged_inputs_require_check(root):
        print("check-derived-sources: SKIP (no staged owning inputs).")
        return 0
    docs = enumerate_docs(root, cached=args.cached)
    all_errors: list[str] = []
    checked = 0
    for doc in sorted(docs):
        errors = check_doc(root, doc, cached=args.cached)
        if errors:
            all_errors.extend(errors)
        # Count only docs that actually declared a derivation.
        try:
            fm = read_front_matter(root, doc, cached=args.cached)
        except yaml.YAMLError:
            fm = None
        if fm and "derives_from" in fm:
            checked += 1
    catalog_errors, catalog_sources = check_system_knowledge_catalog(root, cached=args.cached)
    all_errors.extend(catalog_errors)

    for err in all_errors:
        print(f"check-derived-sources: {err}", file=sys.stderr)

    if all_errors:
        print(
            f"check-derived-sources: FAILED with {len(all_errors)} issue(s).",
            file=sys.stderr,
        )
        return 1

    print(
        f"check-derived-sources: OK ({checked} doc(s) pinned to roadmap sources; "
        f"{catalog_sources} System Knowledge source(s) pinned)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
