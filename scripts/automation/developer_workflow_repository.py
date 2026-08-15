"""Read-only repository, queue, environment, and hook diagnostics."""

from __future__ import annotations

import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

UTC = timezone.utc  # noqa: UP017 - tracked hooks also support system Python 3.10.
MAX_PATHS = 20
MAX_HISTORY_COMMITS = 64
MAX_RECEIPTS = 50
VALIDATION_WARN_SECONDS = 300


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def git_diagnostic(root: Path) -> dict[str, Any]:
    top_level = git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return {"reason_code": "git_repository_unavailable", "status": "unavailable"}
    repo_root = Path(top_level.stdout.strip()).resolve()
    head = git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    branch = git(repo_root, "branch", "--show-current")
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


def index_diagnostic(root: Path) -> dict[str, Any]:
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        return {"reason_code": "git_index_unavailable", "status": "unavailable"}
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


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def git_common_dir(root: Path) -> tuple[Path, Path] | None:
    top_level = git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return None
    repo_root = Path(top_level.stdout.strip()).resolve()
    common = git(repo_root, "rev-parse", "--git-common-dir")
    if common.returncode != 0:
        return None
    raw = Path(common.stdout.strip())
    return repo_root, (raw if raw.is_absolute() else repo_root / raw).resolve()


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def validation_diagnostic(root: Path) -> dict[str, Any]:
    resolved = git_common_dir(root)
    if resolved is None:
        return {"reason_code": "validation_repository_unavailable", "status": "unavailable"}
    repo_root, common_dir = resolved
    state_root = common_dir / "fdai-validation-queue"
    pending_dir = state_root / "pending"
    receipts_dir = state_root / "receipts"
    if not pending_dir.is_dir() and not receipts_dir.is_dir():
        return {"reason_code": "validation_state_unavailable", "status": "unavailable"}
    history_result = git(repo_root, "rev-list", f"--max-count={MAX_HISTORY_COMMITS}", "HEAD")
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
        enqueued_at = parse_timestamp(
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
        validated_at = parse_timestamp(
            payload.get("validated_at") if isinstance(payload, dict) else None
        )
        commit = payload.get("commit") if isinstance(payload, dict) else None
        if validated_at is None or not isinstance(commit, str):
            invalid_records += 1
            continue
        receipt_rows.append((validated_at, commit))
    latencies: list[float] = []
    for validated_at, commit in sorted(receipt_rows, reverse=True)[:MAX_RECEIPTS]:
        committed = git(repo_root, "show", "-s", "--format=%cI", commit)
        committed_at = (
            parse_timestamp(committed.stdout.strip()) if committed.returncode == 0 else None
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


def _database_identity(value: str) -> tuple[str, int | None, str] | None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or not parsed.path:
        return None
    return parsed.hostname.lower(), port, parsed.path.removeprefix("/")


def environment_diagnostic(root: Path) -> dict[str, Any]:
    resolved = git_common_dir(root)
    if resolved is None:
        return {"reason_code": "environment_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    reasons: list[str] = []
    python_paths = [
        Path(item).resolve() for item in os.environ.get("PYTHONPATH", "").split(":") if item
    ]
    foreign_python_paths = [
        path
        for path in python_paths
        if path != repo_root and repo_root not in path.parents and "fdai" in path.as_posix().lower()
    ]
    if foreign_python_paths:
        reasons.append("foreign_pythonpath")
    virtual_env = os.environ.get("VIRTUAL_ENV")
    virtual_env_scope = "unset"
    if virtual_env:
        virtual_env_path = Path(virtual_env).resolve()
        virtual_env_scope = (
            "current_worktree"
            if virtual_env_path == repo_root or repo_root in virtual_env_path.parents
            else "foreign"
        )
        if virtual_env_scope == "foreign":
            reasons.append("foreign_virtual_env")
    database_url = os.environ.get("FDAI_DATABASE_URL", "")
    runtime_dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    database_collision = False
    if database_url and runtime_dsn:
        test_identity = _database_identity(database_url)
        runtime_identity = _database_identity(runtime_dsn)
        database_collision = test_identity is not None and test_identity == runtime_identity
        if database_collision:
            reasons.append("runtime_database_collision")
    return {
        "database_identity_collision": database_collision,
        "foreign_pythonpath_count": len(foreign_python_paths),
        "reason_codes": reasons,
        "runtime_variable_count": sum(name.startswith("FDAI_") for name in os.environ),
        "status": "warning" if reasons else "ok",
        "virtual_env_scope": virtual_env_scope,
    }


def hook_diagnostic(root: Path) -> dict[str, Any]:
    resolved = git_common_dir(root)
    if resolved is None:
        return {"reason_code": "hook_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    index = index_diagnostic(repo_root)
    if index["status"] == "unavailable":
        return {"reason_code": "hook_index_unavailable", "status": "unavailable"}
    hooks_path_result = git(repo_root, "config", "--get", "core.hooksPath")
    hooks_path = hooks_path_result.stdout.strip() if hooks_path_result.returncode == 0 else ""
    reasons: list[str] = []
    if hooks_path != ".githooks":
        reasons.append("repository_hooks_not_installed")
    overlap_paths = index["overlap_paths"]
    if index["overlap_count"]:
        reasons.append("staged_unstaged_overlap")
    manifest_paths = {
        "security/integrity/manifest.json",
        "security/integrity/manifest.json.sig",
    }
    if any(path in manifest_paths for path in overlap_paths):
        reasons.append("integrity_manifest_overlap")
    return {
        "hooks_path_status": "ok" if hooks_path == ".githooks" else "missing",
        "overlap_count": index["overlap_count"],
        "reason_codes": reasons,
        "recovery_codes": [
            code
            for code, applies in (
                ("install_repository_hooks", hooks_path != ".githooks"),
                ("restage_complete_paths", bool(index["overlap_count"])),
                ("preserve_manifest_before_resign", "integrity_manifest_overlap" in reasons),
            )
            if applies
        ],
        "status": "warning" if reasons else "ok",
    }
