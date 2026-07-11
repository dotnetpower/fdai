#!/usr/bin/env python3
"""CI gate: reject disallowed governance effect transitions.

Loads the governance catalog-as-code from a base git ref (the "before" state)
and from the working tree (the "after" state), then runs the pure
:func:`fdai.rule_catalog.schema.governance_transitions.validate_catalog_transition`.
Any per-rule effective-effect transition outside the allowed table - or a raise
to an enforce effect (``deny`` / ``remediate``) that is not listed as an approved
promotion - fails the build.

rule-governance.md requires this gate. The heavy logic lives in the validator
(pure, unit-tested to 100%); this script is only the thin ``git`` boundary that
materializes the two catalog snapshots and reports.

Usage:
    scripts/check-governance-transitions.py [--base REF] [--root DIR]
                                            [--approved FILE]

- ``--base``     git ref for the "before" snapshot (default: ``origin/main``).
- ``--root``     catalog-as-code root (default: ``rule-catalog/governance``).
- ``--approved`` optional file listing approved promotion assignment ids, one
                 per line (``#`` comments and blanks ignored).

A missing catalog root at either snapshot is treated as an empty catalog, so the
gate is a safe no-op until a catalog is populated.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from fdai.rule_catalog.schema.governance_catalog import (
    GovernanceCatalog,
    load_governance_catalog,
)
from fdai.rule_catalog.schema.governance_transitions import validate_catalog_transition

_DEFAULT_BASE = "origin/main"
_DEFAULT_ROOT = "rule-catalog/governance"


def _load_from_tree(root: Path) -> GovernanceCatalog:
    if not root.is_dir():
        return GovernanceCatalog()
    return load_governance_catalog(root)


def _ref_exists(base: str) -> bool:
    """True when ``base`` resolves to a commit in the current repository."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _load_from_ref(base: str, root: str) -> GovernanceCatalog:
    """Materialize ``root`` at git ref ``base`` and load it.

    Uses ``git archive`` so no worktree switch or stash is needed. An invalid
    ``base`` ref is a configuration error and fails loudly (rather than silently
    comparing against an empty baseline); a valid ref whose ``root`` does not
    exist yet (a new catalog) loads as an empty catalog.
    """
    if not _ref_exists(base):
        raise SystemExit(
            f"check-governance-transitions: base ref {base!r} does not resolve to a commit "
            "- pass a valid --base (fetch it in CI first)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            ["git", "archive", "--format=tar", base, "--", root],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            # Valid ref, but the catalog root is absent there -> new catalog.
            return GovernanceCatalog()
        with tempfile.TemporaryFile() as tar_buf:
            tar_buf.write(proc.stdout)
            tar_buf.seek(0)
            with tarfile.open(fileobj=tar_buf) as tar:
                tar.extractall(tmp, filter="data")
        return _load_from_tree(Path(tmp) / root)


def _read_approved(path: Path | None) -> frozenset[str]:
    if path is None:
        return frozenset()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            ids.add(stripped)
    return frozenset(ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Governance effect-transition CI gate.")
    parser.add_argument("--base", default=_DEFAULT_BASE, help="git ref for the before snapshot")
    parser.add_argument("--root", default=_DEFAULT_ROOT, help="catalog-as-code root directory")
    parser.add_argument(
        "--approved", type=Path, default=None, help="file of approved promotion assignment ids"
    )
    args = parser.parse_args(argv)

    previous = _load_from_ref(args.base, args.root)
    current = _load_from_tree(Path(args.root))
    approved = _read_approved(args.approved)

    issues = validate_catalog_transition(
        previous=previous, current=current, promotions_approved=approved
    )
    if not issues:
        print("check-governance-transitions: OK")
        return 0

    print("check-governance-transitions: FAILED", file=sys.stderr)
    for issue in issues:
        print(f"  {issue.assignment_id} / {issue.rule_id}: {issue.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
