#!/usr/bin/env python3
"""Report bounded, read-only FDAI developer workflow diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agent.design_context import required_context, required_validation  # noqa: E402

SCHEMA_VERSION = 1
UTC = timezone.utc  # noqa: UP017 - tracked hooks also support system Python 3.10.
MAX_PATHS = 20
MAX_HISTORY_COMMITS = 64
MAX_RECEIPTS = 50
VALIDATION_WARN_SECONDS = 300


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_diagnostic(root: Path) -> dict[str, Any]:
    top_level = _git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return {
            "reason_code": "git_repository_unavailable",
            "status": "unavailable",
        }
    repo_root = Path(top_level.stdout.strip()).resolve()
    head = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    branch = _git(repo_root, "branch", "--show-current")
    if head.returncode != 0 or branch.returncode != 0:
        return {
            "reason_code": "git_history_unavailable",
            "status": "unavailable",
            "worktree": str(repo_root),
        }
    return {
        "branch": branch.stdout.strip() or "detached",
        "head": head.stdout.strip(),
        "status": "ok",
        "worktree": str(repo_root),
    }


def _index_diagnostic(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        return {
            "reason_code": "git_index_unavailable",
            "status": "unavailable",
        }
    staged = 0
    unstaged = 0
    untracked = 0
    overlaps: list[str] = []
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        index_state, worktree_state = line[0], line[1]
        path = line[3:]
        if index_state == "?" and worktree_state == "?":
            untracked += 1
            continue
        staged += int(index_state != " ")
        unstaged += int(worktree_state != " ")
        if index_state != " " and worktree_state != " ":
            overlaps.append(path)
    return {
        "overlap_count": len(overlaps),
        "overlap_paths": overlaps[:MAX_PATHS],
        "staged_count": staged,
        "status": "warning" if overlaps else "ok",
        "unstaged_count": unstaged,
        "untracked_count": untracked,
    }


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _git_common_dir(root: Path) -> tuple[Path, Path] | None:
    top_level = _git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return None
    repo_root = Path(top_level.stdout.strip()).resolve()
    common = _git(repo_root, "rev-parse", "--git-common-dir")
    if common.returncode != 0:
        return None
    raw = Path(common.stdout.strip())
    return repo_root, (raw if raw.is_absolute() else repo_root / raw).resolve()


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _validation_diagnostic(root: Path) -> dict[str, Any]:
    resolved = _git_common_dir(root)
    if resolved is None:
        return {"reason_code": "validation_repository_unavailable", "status": "unavailable"}
    repo_root, common_dir = resolved
    state_root = common_dir / "fdai-validation-queue"
    pending_dir = state_root / "pending"
    receipts_dir = state_root / "receipts"
    if not pending_dir.is_dir() and not receipts_dir.is_dir():
        return {"reason_code": "validation_state_unavailable", "status": "unavailable"}

    history_result = _git(
        repo_root,
        "rev-list",
        f"--max-count={MAX_HISTORY_COMMITS}",
        "HEAD",
    )
    history = set(history_result.stdout.splitlines()) if history_result.returncode == 0 else set()
    now = datetime.now(UTC)
    pending_ages: list[float] = []
    reachable_pending = 0
    invalid_records = 0
    for path in pending_dir.glob("*.json") if pending_dir.is_dir() else ():
        if path.stem not in history:
            continue
        reachable_pending += 1
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_records += 1
            continue
        enqueued_at = _parse_timestamp(
            payload.get("enqueued_at") if isinstance(payload, dict) else None
        )
        if enqueued_at is None:
            invalid_records += 1
            continue
        pending_ages.append(max(0.0, (now - enqueued_at).total_seconds()))

    receipt_rows: list[tuple[datetime, str]] = []
    for path in receipts_dir.glob("*.json") if receipts_dir.is_dir() else ():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_records += 1
            continue
        validated_at = _parse_timestamp(
            payload.get("validated_at") if isinstance(payload, dict) else None
        )
        commit = payload.get("commit") if isinstance(payload, dict) else None
        if validated_at is None or not isinstance(commit, str):
            invalid_records += 1
            continue
        receipt_rows.append((validated_at, commit))

    latencies: list[float] = []
    for validated_at, commit in sorted(receipt_rows, reverse=True)[:MAX_RECEIPTS]:
        committed = _git(repo_root, "show", "-s", "--format=%cI", commit)
        committed_at = (
            _parse_timestamp(committed.stdout.strip()) if committed.returncode == 0 else None
        )
        if committed_at is None:
            invalid_records += 1
            continue
        latencies.append(max(0.0, (validated_at - committed_at).total_seconds()))

    oldest_pending = max(pending_ages, default=0.0)
    latency_p95 = _percentile_95(latencies)
    warning = oldest_pending > VALIDATION_WARN_SECONDS or (
        latency_p95 is not None and latency_p95 > VALIDATION_WARN_SECONDS
    )
    return {
        "invalid_record_count": invalid_records,
        "latency_p95_seconds": None if latency_p95 is None else round(latency_p95, 3),
        "oldest_pending_seconds": round(oldest_pending, 3),
        "reachable_pending_count": reachable_pending,
        "receipt_sample_count": len(latencies),
        "status": "warning" if warning else "ok",
    }


def status_report(root: Path) -> dict[str, Any]:
    """Build one versioned report without changing repository or process state."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "schema_version": SCHEMA_VERSION,
        "sections": {
            "git": _git_diagnostic(root),
            "index": _index_diagnostic(root),
            "validation": _validation_diagnostic(root),
        },
    }


def _relative_targets(root: Path, targets: list[str]) -> tuple[str, ...] | None:
    resolved = _git_common_dir(root)
    if resolved is None:
        return None
    repo_root, _common_dir = resolved
    relative: set[str] = set()
    for raw in targets:
        candidate = Path(raw)
        absolute = candidate if candidate.is_absolute() else repo_root / candidate
        try:
            relative.add(absolute.resolve().relative_to(repo_root).as_posix())
        except ValueError:
            return None
    return tuple(sorted(relative))


def context_plan_report(root: Path, targets: list[str]) -> dict[str, Any]:
    """Resolve current context and focused checks without recording a design read."""
    relative = _relative_targets(root, targets)
    if relative is None:
        return {
            "read_only": True,
            "reason_code": "context_target_outside_repository",
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
        }
    return {
        "focused_checks": list(required_validation(relative)),
        "read_only": True,
        "required_documents": list(required_context(relative)),
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "targets": list(relative),
    }


def resume_report(root: Path) -> dict[str, Any]:
    """Load the official handover JSON without duplicating its history selection."""
    script = REPO_ROOT / "scripts" / "automation" / "session-handover.py"
    completed = subprocess.run(  # noqa: S603 - fixed repository script and arguments.
        [sys.executable, str(script), "show", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "read_only": True,
            "reason_code": "handover_command_failed",
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
        }
    try:
        payload: object = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return {
            "read_only": True,
            "reason_code": "handover_output_invalid",
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
        }
    return {"read_only": True, **payload}


def _render_text(report: dict[str, Any]) -> str:
    git_state = report["sections"]["git"]
    if git_state["status"] != "ok":
        return f"developer-workflow: unavailable ({git_state['reason_code']})"
    index_state = report["sections"]["index"]
    return (
        "developer-workflow: ok\n"
        f"  worktree: {git_state['worktree']}\n"
        f"  branch:   {git_state['branch']}\n"
        f"  head:     {git_state['head'][:12]}\n"
        f"  index:    {index_state['status']} "
        f"(staged={index_state['staged_count']}, unstaged={index_state['unstaged_count']}, "
        f"untracked={index_state['untracked_count']}, overlap={index_state['overlap_count']})"
    )


def _render_context_plan(report: dict[str, Any]) -> str:
    if report["status"] != "ok":
        return f"developer-workflow: unavailable ({report['reason_code']})"
    lines = ["developer-workflow: context plan"]
    lines.extend(f"  read:  {path}" for path in report["required_documents"])
    lines.extend(f"  check: {command}" for command in report["focused_checks"])
    return "\n".join(lines)


def _render_resume(report: dict[str, Any]) -> str:
    if report["status"] == "unavailable":
        return f"developer-workflow: unavailable ({report['reason_code']})"
    return (
        "developer-workflow: resume\n"
        f"  commit:     {str(report['commit'])[:12]}\n"
        f"  validation: {'validated' if report['validated'] else 'pending'}\n"
        f"  relation:   {report['history_relation']}\n"
        f"  next:       {report['next_action']}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    context_parser = subparsers.add_parser("context-plan")
    context_parser.add_argument("targets", nargs="+")
    context_parser.add_argument("--json", action="store_true", dest="as_json")
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "context-plan":
        report = context_plan_report(Path.cwd(), arguments.targets)
        renderer = _render_context_plan
    elif arguments.command == "resume":
        report = resume_report(Path.cwd())
        renderer = _render_resume
    else:
        report = status_report(Path.cwd())
        renderer = _render_text
    if arguments.as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(renderer(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
