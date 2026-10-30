"""Own the local Bootstrap session, not the Azure deployment identity."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from types import FrameType

import uvicorn
from fdai_deployment_cli.bootstrap_channel import prepare_directory

from fdai_lifecycle_hub.setup_api import SESSION_SECONDS, create_setup_app


@contextmanager
def launcher_lock(state_dir: Path) -> Iterator[None]:
    """Serialize launchers with a kernel lock; a stale PID is never replay authority."""
    prepare_directory(state_dir)
    descriptor = os.open(
        state_dir / "launcher.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Bootstrap is already running for this state directory.") from error
        yield
    finally:
        os.close(descriptor)


def _worker_ready(
    worker: subprocess.Popen[bytes],
    state_dir: Path,
    *,
    started_ns: int,
    stop: Event | None = None,
) -> None:
    """Require the executor's own current startup signal, not process presence alone."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if stop is not None and stop.is_set():
            raise ValueError("Bootstrap startup interrupted; retained setup requires review.")
        if worker.poll() is not None:
            raise ValueError("Bootstrap executor stopped; inspect its private diagnostics.")
        heartbeat = state_dir / "heartbeat.json"
        if heartbeat.is_file() and not heartbeat.is_symlink():
            try:
                record = json.loads(heartbeat.read_bytes())
            except (OSError, ValueError):
                record = None
            if (
                isinstance(record, dict)
                and record.get("pid") == worker.pid
                and heartbeat.stat().st_mtime_ns >= started_ns
            ):
                return
        time.sleep(0.1)
    raise ValueError("Bootstrap executor did not become ready before its startup deadline.")


def start(args: argparse.Namespace) -> int:
    """Start one loopback Hub surface and its independently running local executor."""
    if "FDAI_HUB_REMOTE_CONFIG" in os.environ:
        raise ValueError("Bootstrap is customer-local; it cannot start in a remote Hub profile.")
    if not 0 <= args.port <= 65535:
        raise ValueError("Bootstrap port must be between 0 and 65535.")
    state_dir: Path = args.state_dir.expanduser().absolute()
    stop = Event()
    with launcher_lock(state_dir), _shutdown_signals(stop):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", args.port))
            listener.listen(128)
            port = listener.getsockname()[1]
            origin = f"http://127.0.0.1:{port}"
            launch_token = secrets.token_urlsafe(32)
            app = create_setup_app(state_dir, origin=origin, launch_token=launch_token)
            started_ns = time.time_ns()
            worker = subprocess.Popen(  # noqa: S603 - fixed package entrypoint, no shell
                [
                    sys.executable,
                    "-m",
                    "fdai_deployment_cli.bootstrap_worker",
                    "--state-dir",
                    str(state_dir),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                _worker_ready(worker, state_dir, started_ns=started_ns, stop=stop)
                print(f"Lifecycle Hub Bootstrap: {origin}/setup", flush=True)
                print("Azure access stays in the customer executor. Keep this process running.")
                if args.no_browser:
                    print("Browser launch disabled; restart without --no-browser to sign in.")
                elif not webbrowser.open(f"{origin}/setup#session={launch_token}"):
                    raise ValueError(
                        "Could not open a browser. Start Bootstrap on a browser-equipped host."
                    )
                config = uvicorn.Config(
                    app, host="127.0.0.1", port=port, access_log=False, log_level="warning"
                )
                server = uvicorn.Server(config)
                _serve(server, listener, worker, stop)
            finally:
                _stop_worker(worker)
        finally:
            listener.close()
    return 0


@contextmanager
def _shutdown_signals(stop: Event) -> Iterator[None]:
    # Uvicorn re-raises captured signals; retain a handler until worker cleanup finishes.
    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _stop_worker(worker: subprocess.Popen[bytes]) -> None:
    """Stop only this launcher's process group, including an in-flight local child."""
    if not _signal_worker_group(worker.pid, signal.SIGTERM):
        worker.wait(timeout=5)
        return
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _signal_worker_group(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)
        return
    _signal_worker_group(worker.pid, signal.SIGKILL)


def _signal_worker_group(pid: int, sig: signal.Signals) -> bool:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return False
    return True


def _serve(
    server: uvicorn.Server,
    listener: socket.socket,
    worker: subprocess.Popen[bytes],
    stop: Event,
) -> None:
    import asyncio

    async def supervise() -> None:
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        deadline = time.monotonic() + SESSION_SECONDS
        try:
            while not serving.done():
                if stop.is_set():
                    server.should_exit = True
                if worker.poll() is not None:
                    server.should_exit = True
                    raise ValueError("Bootstrap executor stopped; retained setup requires review.")
                if time.monotonic() >= deadline:
                    server.should_exit = True
                    raise ValueError("Bootstrap session expired; inspect state before resuming.")
                await asyncio.sleep(0.5)
            await serving
        finally:
            server.should_exit = True
            await serving

    asyncio.run(supervise())
