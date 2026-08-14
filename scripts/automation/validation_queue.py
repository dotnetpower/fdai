#!/usr/bin/env python3
"""Batch committed changes through one repository-wide validation queue."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.validation_queue_evidence import structural_gate_digest
from scripts.automation.validation_queue_runner import run_validation
from scripts.automation.validation_queue_support import (
    COMMIT_PATTERN,
    UTC,
    QueuePaths,
    atomic_write,
    git,
    initialize,
    pending_commits,
    queue_paths,
    resolve_commit,
)


def enqueue(paths: QueuePaths, revision: str) -> str:
    initialize(paths)
    commit = resolve_commit(paths, revision)
    if (paths.receipts / f"{commit}.json").is_file():
        return commit
    payload = {
        "commit": commit,
        "enqueued_at": datetime.now(UTC).isoformat(),
        "worktree": str(paths.repo_root),
    }
    atomic_write(paths.pending / f"{commit}.json", json.dumps(payload, sort_keys=True) + "\n")
    return commit


def _commits_in_range(paths: QueuePaths, revision_range: str) -> list[str]:
    output = git("rev-list", "--reverse", revision_range, cwd=paths.repo_root).stdout
    return [commit for commit in output.splitlines() if COMMIT_PATTERN.fullmatch(commit)]


def ensure_range(paths: QueuePaths, revision_range: str) -> list[str]:
    return [enqueue(paths, commit) for commit in _commits_in_range(paths, revision_range)]


def unvalidated_range(paths: QueuePaths, revision_range: str) -> list[str]:
    initialize(paths)
    return [
        commit
        for commit in _commits_in_range(paths, revision_range)
        if not (paths.receipts / f"{commit}.json").is_file()
    ]


def check_commit(paths: QueuePaths, revision: str) -> int:
    initialize(paths)
    commit = resolve_commit(paths, revision)
    if (paths.receipts / f"{commit}.json").is_file():
        print(f"validation-queue: commit is validated: {commit}")
        return 0
    print(
        f"validation-queue: BLOCKED - commit requires integration validation: {commit}",
        file=sys.stderr,
    )
    if _validator_is_active(paths):
        print("  Background validation is active; push does not wait for it.", file=sys.stderr)
    else:
        failed_stage = _last_failed_stage(paths, commit)
        if failed_stage is None:
            failed_stage = _last_reachable_failed_stage(paths, resolve_commit(paths, "HEAD"))
        if failed_stage is not None:
            print(
                f"  Last background validation failed at {failed_stage}.",
                file=sys.stderr,
            )
        print("  Run 'make validation-run' in the dedicated integration session.", file=sys.stderr)
    return 1


def check_structural_gates(paths: QueuePaths, revision: str) -> int:
    """Accept structural-gate evidence only for the exact current snapshot."""
    initialize(paths)
    commit = resolve_commit(paths, revision)
    head = resolve_commit(paths, "HEAD")
    if commit != head:
        print(
            "validation-queue: structural evidence must target the current HEAD",
            file=sys.stderr,
        )
        return 1
    try:
        receipt: object = json.loads(
            (paths.receipts / f"{commit}.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return 1
    if not isinstance(receipt, dict) or receipt.get("validated_head") != commit:
        return 1
    stages = receipt.get("stages")
    expected_digest = structural_gate_digest(paths.repo_root)
    if not isinstance(stages, list) or not any(
        isinstance(stage, dict)
        and stage.get("name") == "structural-gates"
        and stage.get("status") == 0
        and stage.get("input_digest") == expected_digest
        for stage in stages
    ):
        return 1
    print(f"validation-queue: structural gates already validated: {commit}")
    return 0


def run(
    paths: QueuePaths,
    mode: str,
    *,
    wait_for_lock: bool = False,
    target: str | None = None,
) -> int:
    return run_validation(paths, mode, wait_for_lock=wait_for_lock, target=target)


def _background_command(paths: QueuePaths) -> list[str]:
    script = Path(__file__).resolve()
    return [sys.executable, str(script), "drain"]


def _wake_request(paths: QueuePaths) -> str:
    try:
        return paths.wake_request.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def drain(paths: QueuePaths) -> int:
    """Drain batches, reloading validator code when the requested head advances."""
    initialize(paths)
    with paths.wake_lock.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        while True:
            requested = _wake_request(paths)
            target = requested if COMMIT_PATTERN.fullmatch(requested) else None
            result = run(paths, "fast", wait_for_lock=True, target=target)
            time.sleep(0.25)
            if _wake_request(paths) != requested:
                os.execv(sys.executable, _background_command(paths))  # noqa: S606
            return result


def _start_detached_fallback(paths: QueuePaths, environment: dict[str, str]) -> bool:
    command = _background_command(paths)
    nice = shutil.which("nice")
    ionice = shutil.which("ionice")
    if nice is not None:
        command = [nice, "-n", "15", *command]
    if ionice is not None:
        command = [ionice, "-c", "3", *command]
    log_path = paths.state_root / "background.log"
    try:
        with log_path.open("ab") as log_file:
            subprocess.Popen(  # noqa: S603 - fixed local command and repository script.
                command,
                cwd=paths.repo_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError:
        return False
    return True


def wake(paths: QueuePaths) -> int:
    """Start a low-priority validator without waiting for validation to finish."""
    initialize(paths)
    if os.environ.get("FDAI_VALIDATION_AUTOSTART", "1") == "0":
        return 0
    head = resolve_commit(paths, "HEAD")
    if (paths.receipts / f"{head}.json").is_file():
        return 0
    atomic_write(paths.wake_request, head + "\n")
    environment = os.environ.copy()
    environment["FDAI_VALIDATION_BACKGROUND"] = "1"
    systemd_run = shutil.which("systemd-run")
    if systemd_run is not None:
        repository_id = hashlib.sha256(str(paths.state_root).encode()).hexdigest()[:8]
        unit = f"fdai-validation-{repository_id}"
        result = subprocess.run(  # noqa: S603 - fixed systemd-run arguments.
            [
                systemd_run,
                "--user",
                "--quiet",
                "--collect",
                f"--unit={unit}",
                "--property=Nice=15",
                "--property=CPUWeight=10",
                "--property=CPUQuota=180%",
                "--property=IOWeight=10",
                "--property=IOSchedulingClass=idle",
                "--property=MemoryHigh=8G",
                f"--working-directory={paths.repo_root}",
                f"--setenv=PATH={environment.get('PATH', '')}",
                "--setenv=FDAI_VALIDATION_BACKGROUND=1",
                *_background_command(paths),
            ],
            cwd=paths.repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return 0
        systemctl = shutil.which("systemctl")
        if systemctl is not None:
            active = subprocess.run(  # noqa: S603 - fixed local unit query.
                [systemctl, "--user", "--quiet", "is-active", unit],
                cwd=paths.repo_root,
                check=False,
            )
            if active.returncode == 0:
                return 0
    if _start_detached_fallback(paths, environment):
        return 0
    print("validation-queue: failed to start background validator", file=sys.stderr)
    return 1


def _validator_is_active(paths: QueuePaths) -> bool:
    initialize(paths)
    with paths.lock.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return False


def _last_failed_stage(paths: QueuePaths, commit: str) -> str | None:
    try:
        run_record: object = json.loads((paths.runs / f"{commit}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(run_record, dict) or run_record.get("status") == 0:
        return None
    stages = run_record.get("stages")
    if isinstance(stages, list):
        for stage in reversed(stages):
            if not isinstance(stage, dict) or stage.get("status") == 0:
                continue
            name = stage.get("name")
            if isinstance(name, str):
                detail = stage.get("detail")
                return f"{name}/{detail}" if isinstance(detail, str) and detail else name
    return "unknown-stage"


def _last_reachable_failed_stage(paths: QueuePaths, head: str) -> str | None:
    """Describe the earliest reachable pending snapshot that failed validation."""
    pending = pending_commits(paths)
    history = git("rev-list", "--reverse", head, cwd=paths.repo_root).stdout.splitlines()
    for commit in history:
        if commit not in pending:
            continue
        failed_stage = _last_failed_stage(paths, commit)
        if failed_stage is not None:
            return f"{failed_stage} on {commit[:12]}"
    return None


def status(paths: QueuePaths, *, show_all: bool = False) -> int:
    pending = pending_commits(paths)
    head = resolve_commit(paths, "HEAD")
    history = git("rev-list", "--reverse", "--topo-order", head, cwd=paths.repo_root).stdout
    reachable = [commit for commit in history.splitlines() if commit in pending]
    elsewhere = sorted(pending - set(reachable))
    if _validator_is_active(paths):
        validator_state = "active"
    else:
        failed_stage = _last_reachable_failed_stage(paths, head)
        validator_state = f"failed at {failed_stage}" if failed_stage is not None else "idle"
    print(
        f"validation-queue: {len(reachable)} reachable pending commit(s), "
        f"{len(elsewhere)} elsewhere, validator {validator_state}"
    )
    for commit in reachable:
        print(f"  {commit}")
    if show_all:
        for commit in elsewhere:
            print(f"  {commit} (elsewhere)")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    enqueue_parser = subparsers.add_parser("enqueue")
    enqueue_parser.add_argument("revision", nargs="?", default="HEAD")
    ensure_parser = subparsers.add_parser("ensure-range")
    ensure_parser.add_argument("revision_range")
    check_parser = subparsers.add_parser("check-range")
    check_parser.add_argument("revision_range")
    check_commit_parser = subparsers.add_parser("check-commit")
    check_commit_parser.add_argument("revision", nargs="?", default="HEAD")
    structural_parser = subparsers.add_parser("check-structural-gates")
    structural_parser.add_argument("revision", nargs="?", default="HEAD")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--all", action="store_true", dest="all_gates")
    run_parser.add_argument("--wait", action="store_true", dest="wait_for_lock")
    subparsers.add_parser("drain")
    subparsers.add_parser("wake")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--all", action="store_true", dest="all_pending")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = queue_paths()
    if arguments.command == "enqueue":
        commit = enqueue(paths, arguments.revision)
        print(f"validation-queue: enqueued {commit}")
        return 0
    if arguments.command == "ensure-range":
        commits = ensure_range(paths, arguments.revision_range)
        print(f"validation-queue: ensured {len(commits)} commit(s)")
        return 0
    if arguments.command == "check-range":
        missing = unvalidated_range(paths, arguments.revision_range)
        if not missing:
            print("validation-queue: outgoing range is validated")
            return 0
        print(
            "validation-queue: BLOCKED - commits require integration validation:", file=sys.stderr
        )
        for commit in missing:
            print(f"  {commit}", file=sys.stderr)
        print("  Run 'make validation-run' in the dedicated integration session.", file=sys.stderr)
        return 1
    if arguments.command == "check-commit":
        return check_commit(paths, arguments.revision)
    if arguments.command == "check-structural-gates":
        return check_structural_gates(paths, arguments.revision)
    if arguments.command == "run":
        return run(
            paths,
            "all" if arguments.all_gates else "fast",
            wait_for_lock=arguments.wait_for_lock,
        )
    if arguments.command == "drain":
        return drain(paths)
    if arguments.command == "wake":
        return wake(paths)
    return status(paths, show_all=arguments.all_pending)


if __name__ == "__main__":
    raise SystemExit(main())
