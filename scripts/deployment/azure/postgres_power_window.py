#!/usr/bin/env python3
"""Open and close a bounded power window for a stopped development PostgreSQL server.

Subscription governance stops development PostgreSQL Flexible Servers outside working hours.
Scheduled evidence workflows that must read the platform database start a stopped server for one
run and stop it again only when that run started it. A server that was already running is never
stopped. The window never changes server configuration; Terraform drift evidence stays read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = "fdai.database-power-window.v1"
_SERVER_ID = re.compile(
    r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/resourceGroups/[A-Za-z0-9._()-]{1,90}"
    r"/providers/Microsoft\.DBforPostgreSQL/flexibleServers/[a-z0-9][a-z0-9-]{1,61}[a-z0-9]",
    re.IGNORECASE,
)
_READY = "Ready"
_STOPPED = "Stopped"
_TRANSITIONAL = frozenset({"Starting", "Stopping", "Updating", "Restarting"})
_AZ_CALL_TIMEOUT_SECONDS = 120.0

Runner = Callable[[Sequence[str], float], str]


class PowerWindowError(RuntimeError):
    """Raised when the database power state cannot be proven safe for the run."""


@dataclass(frozen=True, slots=True)
class WindowTiming:
    """Bounded waits for one power transition."""

    open_deadline_seconds: float = 900.0
    close_deadline_seconds: float = 600.0
    poll_seconds: float = 15.0


def run_az(arguments: Sequence[str], timeout: float) -> str:
    """Run one Azure CLI call and return its trimmed standard output."""

    completed = subprocess.run(
        ["az", *arguments],
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        reason = detail[-1] if detail else f"exit code {completed.returncode}"
        raise PowerWindowError(f"Azure CLI call failed: {reason}")
    return completed.stdout.strip()


def validate_server_id(server_id: str) -> str:
    """Return the server id when it names exactly one PostgreSQL Flexible Server."""

    if _SERVER_ID.fullmatch(server_id) is None:
        raise PowerWindowError("database power window requires a PostgreSQL Flexible Server id")
    return server_id


def server_state(server_id: str, runner: Runner) -> str:
    """Read the current power state of the server."""

    state = runner(
        [
            "postgres",
            "flexible-server",
            "show",
            "--ids",
            server_id,
            "--query",
            "state",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        _AZ_CALL_TIMEOUT_SECONDS,
    )
    if not state or "\n" in state:
        raise PowerWindowError("PostgreSQL server returned no single power state")
    return state


def _wait_for(
    server_id: str,
    targets: frozenset[str],
    *,
    runner: Runner,
    deadline_seconds: float,
    poll_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> str:
    deadline = monotonic() + deadline_seconds
    state = server_state(server_id, runner)
    while state not in targets:
        if state not in _TRANSITIONAL:
            raise PowerWindowError(f"PostgreSQL server is in unsupported state {state!r}")
        if monotonic() >= deadline:
            raise PowerWindowError(f"PostgreSQL server stayed in state {state!r} past the deadline")
        sleep(poll_seconds)
        state = server_state(server_id, runner)
    return state


def _write_record(path: Path, record: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_record(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise PowerWindowError("database power window record is malformed")
    if not isinstance(payload.get("started_by_run"), bool):
        raise PowerWindowError("database power window record has no start claim")
    validate_server_id(str(payload.get("server_id", "")))
    return payload


def open_window(
    server_id: str,
    record_path: Path,
    *,
    runner: Runner = run_az,
    timing: WindowTiming | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Make the server Ready, claiming the start before requesting it."""

    validate_server_id(server_id)
    timing = timing or WindowTiming()
    if record_path.exists() or record_path.is_symlink():
        raise PowerWindowError("database power window record already exists")
    initial = _wait_for(
        server_id,
        frozenset({_READY, _STOPPED}),
        runner=runner,
        deadline_seconds=timing.open_deadline_seconds,
        poll_seconds=timing.poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "server_id": server_id,
        "server_id_sha256": hashlib.sha256(server_id.casefold().encode()).hexdigest(),
        "initial_state": initial,
        "started_by_run": initial == _STOPPED,
        "opened_at": now().isoformat(),
    }
    # The claim precedes the start request so an interrupted run still restores the state.
    _write_record(record_path, record)
    if initial == _READY:
        print("PostgreSQL server was already Ready; the run will not stop it.")
        return record
    print("PostgreSQL server is Stopped; starting it for this run.")
    runner(
        [
            "postgres",
            "flexible-server",
            "start",
            "--ids",
            server_id,
            "--no-wait",
            "--only-show-errors",
        ],
        _AZ_CALL_TIMEOUT_SECONDS,
    )
    _wait_for(
        server_id,
        frozenset({_READY}),
        runner=runner,
        deadline_seconds=timing.open_deadline_seconds,
        poll_seconds=timing.poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    print("PostgreSQL server is Ready.")
    return record


def close_window(
    record_path: Path,
    *,
    runner: Runner = run_az,
    timing: WindowTiming | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Stop the server only when this run's claim says the run started it."""

    timing = timing or WindowTiming()
    if not record_path.exists():
        print("No database power window was opened; nothing to restore.")
        return "not-opened"
    record = _read_record(record_path)
    if not record["started_by_run"]:
        print("PostgreSQL server was Ready before the run; leaving it Ready.")
        return "left-ready"
    server_id = str(record["server_id"])
    state = _wait_for(
        server_id,
        frozenset({_READY, _STOPPED}),
        runner=runner,
        deadline_seconds=timing.close_deadline_seconds,
        poll_seconds=timing.poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    if state == _STOPPED:
        print("PostgreSQL server is already Stopped.")
        return "already-stopped"
    runner(
        [
            "postgres",
            "flexible-server",
            "stop",
            "--ids",
            server_id,
            "--no-wait",
            "--only-show-errors",
        ],
        _AZ_CALL_TIMEOUT_SECONDS,
    )
    _wait_for(
        server_id,
        frozenset({_STOPPED}),
        runner=runner,
        deadline_seconds=timing.close_deadline_seconds,
        poll_seconds=timing.poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    print("PostgreSQL server restored to Stopped.")
    return "stopped"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    opened = commands.add_parser("open")
    opened.add_argument("--server-id", required=True)
    opened.add_argument("--record", type=Path, required=True)
    closed = commands.add_parser("close")
    closed.add_argument("--record", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "open":
            open_window(args.server_id, args.record)
        else:
            close_window(args.record)
    except (PowerWindowError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"database power window failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
