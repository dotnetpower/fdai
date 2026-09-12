#!/usr/bin/env python3
"""Start or inspect one bounded local coordinator for a published pull request."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.pr_delivery_daemon_runtime import DeliveryDaemon  # noqa: E402
from scripts.automation.pr_delivery_daemon_support import (  # noqa: E402
    DeliveryConfig,
    DeliveryError,
    Runner,
)
from scripts.automation.pr_delivery_daemon_support import (  # noqa: E402
    default_runner as _default_runner,
)
from scripts.automation.pr_delivery_daemon_support import (  # noqa: E402
    delivery_paths as _paths,
)
from scripts.automation.pr_delivery_daemon_support import (  # noqa: E402
    is_matching_process as _is_matching_process,
)
from scripts.automation.pr_delivery_daemon_support import (  # noqa: E402
    read_state as _read_state,
)


def _config_from_args(args: argparse.Namespace) -> DeliveryConfig:
    return DeliveryConfig(
        repository=args.repo,
        pr_number=args.pr_number,
        topic_branch=args.topic_branch,
        base_branch=args.base_branch,
        worktree=Path(args.worktree).resolve(),
        remote=args.remote,
        merge_method=args.merge_method,
        interval_seconds=args.interval_seconds,
        total_timeout_seconds=args.total_timeout_seconds,
        no_progress_seconds=args.no_progress_seconds,
        command_timeout_seconds=args.command_timeout_seconds,
    )


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--topic-branch", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--merge-method", choices=("merge", "rebase", "squash"), default="squash")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--total-timeout-seconds", type=int, default=3600)
    parser.add_argument("--no-progress-seconds", type=int, default=1200)
    parser.add_argument("--command-timeout-seconds", type=int, default=900)


def _start(config: DeliveryConfig, runner: Runner = _default_runner) -> int:
    """Create one detached daemon and wait for its lock-owned state handoff."""
    config.validate()
    paths = _paths(runner, config)
    paths.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(paths.directory, 0o700)
    with paths.launch_lock.open("a+", encoding="utf-8") as launch_lock:
        os.chmod(paths.launch_lock, 0o600)
        fcntl.flock(launch_lock, fcntl.LOCK_EX)
        existing = _read_state(paths.state)
        if existing and not existing.get("terminal"):
            pid = existing.get("pid")
            if _is_matching_process(pid, config):
                print(json.dumps({"event": "reused", "pid": pid, "state": str(paths.state)}))
                return 0
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "run",
            "--repo",
            config.repository,
            "--pr-number",
            str(config.pr_number),
            "--topic-branch",
            config.topic_branch,
            "--base-branch",
            config.base_branch,
            "--worktree",
            str(config.worktree),
            "--remote",
            config.remote,
            "--merge-method",
            config.merge_method,
            "--interval-seconds",
            str(config.interval_seconds),
            "--total-timeout-seconds",
            str(config.total_timeout_seconds),
            "--no-progress-seconds",
            str(config.no_progress_seconds),
            "--command-timeout-seconds",
            str(config.command_timeout_seconds),
        ]
        with paths.log.open("ab") as log:
            os.chmod(paths.log, 0o600)
            process = subprocess.Popen(  # noqa: S603 - fixed interpreter and validated arguments.
                command,
                cwd=config.worktree,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        handoff_deadline = time.monotonic() + 5
        while time.monotonic() < handoff_deadline:
            state = _read_state(paths.state)
            if state and state.get("pid") == process.pid:
                if state.get("terminal"):
                    raise DeliveryError("delivery daemon failed during startup")
                break
            if process.poll() is not None:
                raise DeliveryError("delivery daemon exited before acquiring its lock")
            time.sleep(0.05)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            raise DeliveryError("delivery daemon did not acquire its lock within 5 seconds")
        print(
            json.dumps(
                {
                    "event": "started",
                    "pid": process.pid,
                    "state": str(paths.state),
                    "log": str(paths.log),
                },
                sort_keys=True,
            )
        )
    return 0


def _status(config: DeliveryConfig, runner: Runner = _default_runner) -> int:
    """Print one private state snapshot without contacting GitHub."""
    config.validate()
    paths = _paths(runner, config)
    state = _read_state(paths.state)
    print(json.dumps(state or {"phase": "absent", "terminal": True}, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    for operation in ("start", "run", "status"):
        command = operations.add_parser(operation)
        _add_config_arguments(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _config_from_args(args)
        if args.operation == "start":
            return _start(config)
        if args.operation == "status":
            return _status(config)
        coordinator = DeliveryDaemon(config)
        signal.signal(signal.SIGINT, lambda *_: coordinator.stop_event.set())
        signal.signal(signal.SIGTERM, lambda *_: coordinator.stop_event.set())
        return coordinator.run()
    except DeliveryError as error:
        print(f"pr-delivery-daemon: ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
