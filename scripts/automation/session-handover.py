#!/usr/bin/env python3
"""Record and show concise local coding-session handovers."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=check,
    )


def _paths(root: Path) -> tuple[Path, Path]:
    repo_root = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    raw_common = Path(_git(repo_root, "rev-parse", "--git-common-dir").stdout.strip())
    common = raw_common if raw_common.is_absolute() else repo_root / raw_common
    return repo_root, common.resolve() / "fdai-handovers"


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def record(root: Path, revision: str) -> int:
    """Persist a concise handover for one committed revision."""
    repo_root, state = _paths(root)
    commit = _git(repo_root, "rev-parse", "--verify", f"{revision}^{{commit}}").stdout.strip()
    subject = _git(repo_root, "show", "-s", "--format=%s", commit).stdout.strip()
    branch = _git(repo_root, "branch", "--show-current").stdout.strip() or "detached"
    changed_files = _git(
        repo_root,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit,
    ).stdout.splitlines()
    payload = {
        "branch": branch,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files[:20],
        "commit": commit,
        "recorded_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - system Python 3.10.
        "schema_version": 1,
        "subject": subject,
        "worktree": str(repo_root),
    }
    _atomic_json(state / "records" / f"{commit}.json", payload)
    _atomic_json(state / "latest.json", payload)
    return 0


def _load_relevant(root: Path, state: Path) -> dict[str, object] | None:
    records = sorted(
        (state / "records").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    fallback: dict[str, object] | None = None
    for path in records:
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("commit"), str):
            continue
        fallback = fallback or payload
        if (
            _git(
                root,
                "merge-base",
                "--is-ancestor",
                str(payload["commit"]),
                "HEAD",
                check=False,
            ).returncode
            == 0
        ):
            return payload
    return fallback


def show(root: Path) -> int:
    """Print the latest handover relevant to the current history."""
    repo_root, state = _paths(root)
    payload = _load_relevant(repo_root, state)
    if payload is None:
        print("(no automatic handover recorded)")
        return 0
    commit = str(payload["commit"])
    raw_common = Path(_git(repo_root, "rev-parse", "--git-common-dir").stdout.strip())
    common = raw_common if raw_common.is_absolute() else repo_root / raw_common
    validated = (
        common.resolve() / "fdai-validation-queue" / "receipts" / f"{commit}.json"
    ).is_file()
    changed = payload.get("changed_files")
    files = changed if isinstance(changed, list) else []
    print(f"commit:     {commit[:12]} {payload.get('subject', '')}")
    print(f"branch:     {payload.get('branch', 'unknown')}")
    print(f"worktree:   {payload.get('worktree', 'unknown')}")
    print(f"files:      {payload.get('changed_file_count', len(files))}")
    for path in files[:5]:
        print(f"  {path}")
    print(f"validation: {'validated' if validated else 'pending'}")
    if validated:
        print("next:       inspect the current working tree and continue the next focused batch")
    else:
        print("next:       let the Integration Validator drain this commit before external work")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("revision", nargs="?", default="HEAD")
    subparsers.add_parser("show")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.command == "record":
        return record(Path.cwd(), arguments.revision)
    return show(Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
