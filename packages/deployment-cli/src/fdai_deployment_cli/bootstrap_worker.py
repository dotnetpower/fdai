"""Attached customer executor: ``python -m fdai_deployment_cli.bootstrap_worker``."""

from __future__ import annotations

import argparse
import fcntl
import json
import multiprocessing
import os
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess
from pathlib import Path
from types import FrameType
from uuid import uuid4

from fdai_deployment_cli.bootstrap_channel import (
    _read,
    _write,
    initial_status,
    locked,
    prepare_directory,
    validate_request,
)
from fdai_deployment_cli.bootstrap_executor import BootstrapBlocked, BootstrapExecutor
from fdai_deployment_cli.bootstrap_support import (
    failure_diagnostic_message,
    latest_progress_message,
)

TOTAL_SECONDS = 8 * 3600
OPERATION_SECONDS = {
    "login": 660,
    "accounts": 120,
    "inspect": 120,
    "reset": 120,
    "install": 14400,
    "resume": 14400,
}
NO_PROGRESS_SECONDS = 1800


def _update(root: Path, **fields: object) -> None:
    with locked(root):
        record = _read(root)
        status = record.get("status", initial_status())
        status.update(fields)
        record.update(status=status, progress=time.time())
        _write(root, record)


def channel_decision(root: Path, review: dict[str, object]) -> dict[str, object]:
    """Expose one safe exact review and consume only its current one-shot decision."""
    expires = datetime.fromisoformat(str(review["expires_at"]))
    remaining = min(600, (expires - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        raise ValueError("Exact checkpoint expired before review")
    current = {
        "id": str(uuid4()),
        "digest": review["digest"],
        "title": review["title"],
        "details": review["details"],
        "confirmation_required": review["confirmation_required"],
        "expires_at": review["expires_at"],
    }
    if len(json.dumps(current, allow_nan=False).encode()) > 16384:
        raise BootstrapBlocked(
            "Exact plan exceeds the bounded browser review. Inspect its retained plan "
            "with the existing CLI; no browser approval was granted."
        )
    _update(
        root,
        phase="review",
        review=current,
        message="Review this exact checkpoint before continuing.",
    )
    deadline = time.monotonic() + remaining
    while time.monotonic() < deadline:
        with locked(root):
            record = _read(root)
            decision = record.get("decision")
            if decision is not None:
                status = record["status"]
                if (
                    not isinstance(decision, dict)
                    or decision.get("request_id") != status["request_id"]
                    or decision.get("review_id") != current["id"]
                    or decision.get("digest") != current["digest"]
                ):
                    raise ValueError("Current checkpoint decision binding changed")
                record["decision"] = None
                _write(root, record)
                return decision
        time.sleep(0.1)
    raise TimeoutError("Exact checkpoint decision expired; no approval was granted")


def run_request(
    root: Path,
    request: dict[str, object],
    *,
    executor_factory: Callable[
        [Path, Callable[[dict[str, object]], dict[str, object]]], BootstrapExecutor
    ] = BootstrapExecutor,
) -> None:
    """Execute a claimed request; failures never expose raw exception or process output."""
    action = str(request["action"])
    try:
        raw_payload = request["payload"]
        if not isinstance(raw_payload, dict):
            raise ValueError("Malformed executor request")  # noqa: TRY004 - IPC rejection contract
        payload = validate_request(action, raw_payload)
        executor = executor_factory(
            root / "executor", lambda review: channel_decision(root, review)
        )
        if action == "login":
            _update(root, message="Complete Microsoft browser sign-in on this customer machine.")
        result = executor.execute(action, payload)
        ready = result.get("deployment_ready") is True
        retained = bool(_read(root / "executor", "configuration.json"))
        message = result.get("message", "Customer executor operation completed.")
        if retained and action in {"login", "accounts", "inspect"}:
            message = "Retained installation preserved. Resume to refresh its exact target, plans and health."
        _update(
            root,
            phase="ready"
            if ready
            else "blocked"
            if action in {"install", "resume"} or retained
            else "idle",
            request_id=request["id"] if retained or action in {"install", "resume"} else None,
            review=None,
            error_code=None,
            deployment_ready=ready,
            console_url=result.get("console_url") if ready else None,
            message=message,
            **({"accounts": result["accounts"]} if "accounts" in result else {}),
        )
    except BootstrapBlocked as exc:
        _update(
            root,
            phase="blocked",
            review=None,
            deployment_ready=False,
            console_url=None,
            error_code="prerequisite_unavailable",
            message=str(exc),
        )
    except (TimeoutError, subprocess.TimeoutExpired):
        _update(
            root,
            phase="interrupted",
            review=None,
            deployment_ready=False,
            console_url=None,
            error_code="operation_timeout",
            message="Operation expired. Inspect retained state; do not repeat ambiguous effects.",
        )
    except Exception:  # noqa: BLE001 - executor boundary must never publish raw provider errors
        _update(
            root,
            phase="failed",
            review=None,
            deployment_ready=False,
            console_url=None,
            error_code="executor_failed",
            message=failure_diagnostic_message(root),
        )


def _child(root: Path, request: dict[str, object], output: int, reader: int, parent: int) -> None:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    os.umask(0o077)
    os.close(reader)
    area = root / "executor"
    prepare_directory(area)
    os.dup2(output, 1)
    os.dup2(output, 2)
    os.close(output)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)

    def parent_watchdog() -> None:
        while os.getppid() == parent:
            time.sleep(0.25)
        # A forced worker kill must also stop the isolated operation's descendants.
        os.killpg(os.getpid(), signal.SIGKILL)

    threading.Thread(target=parent_watchdog, daemon=True).start()
    run_request(root, request)


def _trace(root: Path) -> int:
    area = root / "executor"
    prepare_directory(area)
    current, previous = area / "engine-trace.log", area / "engine-trace.previous.log"
    if current.is_symlink() or previous.is_symlink():
        raise ValueError("Private executor traces must not be symlinks")
    if current.exists():
        info = current.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("Private executor trace is unsafe")
        os.replace(current, previous)
    fd = os.open(current, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        os.close(fd)
        raise ValueError("Private executor trace is unsafe")
    return fd


def _drain(reader: int, trace: int) -> bool:
    """Keep engine traces bounded without limiting Terraform state or artifact file sizes."""
    for _ in range(64):
        try:
            data = os.read(reader, 4096)
        except BlockingIOError:
            break
        if not data:
            break
        if os.fstat(trace).st_size + len(data) > 16 * 1024 * 1024:
            return False
        os.write(trace, data)
    return True


def _stop(process: BaseProcess) -> None:
    if process.is_alive() and process.pid is not None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.terminate()
        process.join(5)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.join(5)
    elif process.pid is not None:
        # Also remove children left behind by a crashed operation coordinator.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def serve(root: Path, *, total_seconds: int = TOTAL_SECONDS) -> None:
    """Supervise serial process groups with heartbeat, hard deadlines and no replay."""
    prepare_directory(root)
    os.umask(0o077)
    lock = os.open(root / "worker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(lock)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
    ):
        os.close(lock)
        raise ValueError("Worker lock is unsafe")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(lock)
        raise ValueError("A customer executor already owns this directory") from exc
    stopping = False

    def stop(_signal: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    process = None
    reader = trace_fd = None
    started = time.monotonic()
    operation_started = started
    progress_time = started
    last_progress = None
    action = ""
    try:
        with locked(root):
            record = _read(root)
            status = record.get("status", initial_status())
            if (
                status["phase"] in {"working", "review"}
                or record.get("pending")
                or record.get("active_request_id")
            ):
                status.update(
                    phase="interrupted",
                    review=None,
                    deployment_ready=False,
                    console_url=None,
                    error_code="worker_restarted",
                    message="Prior work was interrupted. Inspect retained state before explicit resume.",
                )
            record.update(
                status=status,
                pending=None,
                active_request_id=None,
                decision=None,
                heartbeat=time.time(),
            )
            _write(root, record)
        while not stopping and time.monotonic() - started < min(total_seconds, TOTAL_SECONDS):
            with locked(root):
                record = _read(root)
                record["heartbeat"] = time.time()
                _write(root, record)
                _write(
                    root,
                    {
                        "pid": os.getpid(),
                        "operation_pid": process.pid if process is not None else None,
                        "updated_at": datetime.now(UTC).isoformat(),
                        "heartbeat": time.time(),
                    },
                    "heartbeat.json",
                )
                pending = record.get("pending") if process is None else None
                if pending is not None:
                    record.update(
                        pending=None, active_request_id=pending["id"], progress=time.time()
                    )
                    _write(root, record)
            if pending is not None:
                action = str(pending["action"])
                trace_fd = _trace(root)
                reader, writer = os.pipe()
                os.set_blocking(reader, False)
                process = multiprocessing.get_context("fork").Process(
                    target=_child, args=(root, pending, writer, reader, os.getpid())
                )
                process.start()
                os.close(writer)
                with locked(root):
                    _write(
                        root,
                        {
                            "pid": os.getpid(),
                            "operation_pid": process.pid,
                            "updated_at": datetime.now(UTC).isoformat(),
                            "heartbeat": time.time(),
                        },
                        "heartbeat.json",
                    )
                operation_started = progress_time = time.monotonic()
                last_progress = None
            if process is not None:
                assert reader is not None and trace_fd is not None
                trace_within_bound = _drain(reader, trace_fd)
                trace = root / "executor/engine-trace.log"
                trace_size = (
                    trace.stat().st_size if trace.is_file() and not trace.is_symlink() else 0
                )
                progress = (record.get("progress"), trace_size)
                if progress != last_progress:
                    last_progress, progress_time = progress, time.monotonic()
                    if action in {"install", "resume"}:
                        with locked(root):
                            record = _read(root)
                            if record.get("status", {}).get("phase") == "working":
                                next_msg = latest_progress_message(
                                    root, str(record["status"].get("message", ""))
                                )
                                if next_msg != record["status"].get("message"):
                                    record["status"]["message"] = next_msg
                                    _write(root, record)
                timed_out = (
                    time.monotonic() - operation_started > OPERATION_SECONDS.get(action, 120)
                    or time.monotonic() - progress_time > NO_PROGRESS_SECONDS
                    or not trace_within_bound
                )
                if timed_out or not process.is_alive():
                    _drain(reader, trace_fd)
                    _stop(process)
                    with locked(root):
                        record = _read(root)
                        status = record["status"]
                        if timed_out or status["phase"] in {"working", "review"}:
                            status.update(
                                phase="interrupted",
                                review=None,
                                deployment_ready=False,
                                console_url=None,
                                error_code="operation_interrupted",
                                message="Executor stopped. Inspect retained evidence before explicit resume.",
                            )
                        record.update(status=status, active_request_id=None, progress=time.time())
                        _write(root, record)
                    process.close()
                    process = None
                    os.close(reader)
                    os.close(trace_fd)
                    reader = trace_fd = None
            time.sleep(2)
    finally:
        if process is not None:
            _stop(process)
            process.close()
            _update(
                root,
                phase="interrupted",
                review=None,
                deployment_ready=False,
                console_url=None,
                error_code="worker_stopped",
                message="Worker stopped; inspect before explicit resume.",
            )
        if reader is not None:
            os.close(reader)
        if trace_fd is not None:
            os.close(trace_fd)
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)
        os.close(lock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.state_dir.absolute()
    try:
        serve(root)
    except Exception:  # noqa: BLE001 - startup errors must not leak paths or provider diagnostics
        prepare_directory(root)
        area = root / "executor"
        prepare_directory(area)
        _write(
            area,
            {
                "error_code": "worker_startup_failed",
                "message": "Worker startup failed. Check private directory permissions and worker ownership.",
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            "worker-diagnostics.json",
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
