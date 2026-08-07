"""Process lifecycle owned by the isolated Executor distribution."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
from collections.abc import Callable, Coroutine
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

_LOGGER = logging.getLogger("fdai.isolated_executor.startup")


def install_shutdown_signals() -> asyncio.Event:
    """Return an event set by SIGTERM or SIGINT."""

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_stop(signame: str) -> None:
        _LOGGER.info("shutdown_signal", extra={"signal": signame})
        stop.set()

    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(handled_signal, signal_stop, handled_signal.name)
    return stop


@contextmanager
def executor_process_lock() -> Any:
    """Hold the optional service process lock for the complete runtime."""

    raw_path = os.environ.get("FDAI_ISOLATED_EXECUTOR_LOCK_FILE", "").strip()
    if not raw_path:
        yield
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream: IO[str] = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"isolated Executor is already active for {path}") from exc
        yield
    finally:
        stream.close()


def run_main(run: Callable[[], Coroutine[Any, Any, int]]) -> int:
    """Run one service coroutine under logging and process-lock ownership."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
        force=True,
    )
    try:
        with executor_process_lock():
            return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


__all__ = ["executor_process_lock", "install_shutdown_signals", "run_main"]
