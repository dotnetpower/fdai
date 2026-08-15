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

MAX_CHANGED_FILES = 20


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


def _worktree_status(root: Path) -> dict[str, object]:
    result = _git(root, "status", "--porcelain=v1", "--untracked-files=all", check=False)
    if result.returncode != 0:
        return {"reason_code": "git_index_unavailable", "status": "unavailable"}
    paths = [line[3:] for line in result.stdout.splitlines() if len(line) >= 4]
    overlaps = [
        line[3:]
        for line in result.stdout.splitlines()
        if len(line) >= 4 and line[0] not in {" ", "?"} and line[1] not in {" ", "?"}
    ]
    return {
        "changed_count": len(paths),
        "changed_files": paths[:MAX_CHANGED_FILES],
        "overlap_count": len(overlaps),
        "status": "warning" if overlaps else "ok",
    }


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
        "changed_files": changed_files[:MAX_CHANGED_FILES],
        "commit": commit,
        "recorded_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - system Python 3.10.
        "schema_version": 2,
        "subject": subject,
        "worktree": str(repo_root),
        "worktree_status": _worktree_status(repo_root),
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


def show_report(root: Path) -> dict[str, object]:
    """Return the latest relevant handover with current drift and validation state."""
    repo_root, state = _paths(root)
    payload = _load_relevant(repo_root, state)
    if payload is None:
        return {
            "reason_code": "handover_unavailable",
            "schema_version": 2,
            "status": "unavailable",
        }
    commit = str(payload["commit"])
    raw_common = Path(_git(repo_root, "rev-parse", "--git-common-dir").stdout.strip())
    common = raw_common if raw_common.is_absolute() else repo_root / raw_common
    validated = (
        common.resolve() / "fdai-validation-queue" / "receipts" / f"{commit}.json"
    ).is_file()
    current_head = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    reachable = (
        _git(repo_root, "merge-base", "--is-ancestor", commit, current_head, check=False).returncode
        == 0
    )
    return {
        **payload,
        "current_head": current_head,
        "current_worktree_status": _worktree_status(repo_root),
        "history_relation": "reachable" if reachable else "divergent",
        "next_action": (
            "inspect_worktree_and_continue" if validated else "wait_for_integration_validation"
        ),
        "status": "ok" if reachable else "warning",
        "validated": validated,
    }


def show(root: Path, *, as_json: bool = False) -> int:
    """Print the latest handover relevant to the current history."""
    report = show_report(root)
    if as_json:
        print(json.dumps(report, sort_keys=True))
        return 0
    if report["status"] == "unavailable":
        print("(no automatic handover recorded)")
        return 0
    commit = str(report["commit"])
    changed = report.get("changed_files")
    files = changed if isinstance(changed, list) else []
    print(f"commit:     {commit[:12]} {report.get('subject', '')}")
    print(f"branch:     {report.get('branch', 'unknown')}")
    print(f"worktree:   {report.get('worktree', 'unknown')}")
    print(f"files:      {report.get('changed_file_count', len(files))}")
    for path in files[:5]:
        print(f"  {path}")
    print(f"validation: {'validated' if report['validated'] else 'pending'}")
    current_status = report.get("current_worktree_status")
    if isinstance(current_status, dict):
        print(f"drift:      {current_status.get('changed_count', 'unknown')} changed path(s)")
    if report["validated"]:
        print("next:       inspect the current working tree and continue the next focused batch")
    else:
        print("next:       let the Integration Validator drain this commit before external work")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("revision", nargs="?", default="HEAD")
    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.command == "record":
        return record(Path.cwd(), arguments.revision)
    return show(Path.cwd(), as_json=arguments.as_json)


if __name__ == "__main__":
    raise SystemExit(main())
