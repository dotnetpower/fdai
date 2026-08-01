#!/usr/bin/env python3
"""Run one roadmap verification job while interactive sessions are idle."""

from __future__ import annotations

import argparse
import fcntl
import os
import time
from pathlib import Path
from typing import TextIO

import roadmap_verification as queue
import roadmap_verification_worker as worker


def _active_session_leases(repo_root: Path, idle_seconds: int) -> list[str]:
    lease_dir = repo_root / ".improve" / "sessions"
    if not lease_dir.is_dir():
        return []
    now = time.time()
    active: list[str] = []
    for lease in lease_dir.glob("*.lease"):
        try:
            age = now - lease.stat().st_mtime
        except OSError:
            continue
        if age <= idle_seconds:
            active.append(lease.stem)
        elif age > max(idle_seconds * 8, 86_400):
            lease.unlink(missing_ok=True)
    return sorted(active)


def _recent_copilot_activity(idle_seconds: int) -> list[str]:
    configured = os.environ.get("FDAI_VSCODE_WORKSPACE_STORAGE", "").strip()
    storage = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".vscode-server/data/User/workspaceStorage"
    )
    if not storage.is_dir():
        return []
    cutoff = time.time() - idle_seconds
    markers = (
        "*/GitHub.copilot-chat/transcripts/*.jsonl",
        "*/GitHub.copilot-chat/debug-logs/*/main.jsonl",
    )
    active: set[str] = set()
    for path in (candidate for pattern in markers for candidate in storage.glob(pattern)):
        try:
            if path.stat().st_mtime >= cutoff:
                active.add(path.stem)
        except OSError:
            continue
    return sorted(active)


def _acquire_lock(path: Path) -> TextIO | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    os.chmod(path, 0o600)
    return handle


def run_cycle(
    paths: queue.QueuePaths,
    *,
    apply: bool,
    force: bool,
    idle_seconds: int,
    lease_seconds: int,
    timeout: int,
    base_ref: str,
    integrate: bool,
) -> str:
    if (paths.state_root / "STOP").exists() or (paths.repo_root / ".improve/STOP").exists():
        return "held: stop file present"
    lock = _acquire_lock(paths.state_root / "watchdog.lock")
    if lock is None:
        return "held: another watchdog is active"
    with lock:
        leases = _active_session_leases(paths.repo_root, idle_seconds)
        sessions = _recent_copilot_activity(idle_seconds)
        if not force and (leases or sessions):
            reasons: list[str] = []
            if leases:
                reasons.append(f"session-leases={len(leases)}")
            if sessions:
                reasons.append(f"recent-copilot-sessions={len(sessions)}")
            return "held: " + ", ".join(reasons)
        result = worker.run_one(
            paths,
            apply=apply,
            base_ref=base_ref,
            lease_seconds=lease_seconds,
            timeout=timeout,
            integrate=integrate,
        )
        return "idle: no eligible job" if result is None else f"completed: {result['document']}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--idle-seconds", type=int, default=900)
    parser.add_argument("--lease-seconds", type=int, default=5400)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--integrate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = queue.queue_paths()
    message = run_cycle(
        paths,
        apply=arguments.apply,
        force=arguments.force,
        idle_seconds=max(60, arguments.idle_seconds),
        lease_seconds=max(60, arguments.lease_seconds),
        timeout=max(60, arguments.timeout),
        base_ref=arguments.base_ref,
        integrate=arguments.integrate,
    )
    print(f"roadmap-verification watchdog {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
