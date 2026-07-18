"""Structured JSON logging with ``correlation_id`` auto-injection.

Design rules (see ``coding-conventions.instructions.md``):

- Emit **JSON, one object per line** - machines parse, humans grep.
- Every line carries an ISO 8601 UTC timestamp, log level, logger name,
  message, and - when set - ``correlation_id`` from
  :mod:`fdai.shared.telemetry.correlation`.
- Never dump raw event payloads or secrets. Callers pass structured
  ``extra`` dicts that they have already redacted.
- ``configure_logging`` is idempotent so a re-entered composition root
  does not stack handlers.
- Local source-checkout runs can persist ``WARNING`` and higher records in
    a process-locked JSONL file that retains a rolling 24-hour window.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from .correlation import current_correlation_id

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class JsonFormatter(logging.Formatter):
    """One JSON object per :class:`logging.LogRecord`."""

    # Attributes on LogRecord that ``logging`` sets by default; anything
    # else in ``record.__dict__`` was added via ``logger.info(..., extra=...)``
    # and should show up in the emitted line.
    _RESERVED = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": current_correlation_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for k, v in record.__dict__.items():
            if k in self._RESERVED or k.startswith("_"):
                continue
            payload[k] = v

        return json.dumps(payload, ensure_ascii=True, default=str)


_HANDLER_MARKER = "_fdai_json_handler"
_DEFAULT_WARNING_RETENTION = timedelta(hours=24)
_DEFAULT_CLEANUP_INTERVAL_SECONDS = 300.0


class RetainedJsonlHandler(logging.Handler):
    """Append JSONL records while retaining only a rolling time window."""

    def __init__(
        self,
        path: Path,
        *,
        retention: timedelta = _DEFAULT_WARNING_RETENTION,
        cleanup_interval_seconds: float = _DEFAULT_CLEANUP_INTERVAL_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        if retention <= timedelta(0):
            raise ValueError("log retention MUST be positive")
        if cleanup_interval_seconds <= 0:
            raise ValueError("log cleanup interval MUST be positive")
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")
        self._retention = retention
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._compact(self._clock())
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="fdai-warning-log-retention",
            daemon=True,
        )
        self._cleanup_thread.start()

    @property
    def path(self) -> Path:
        """Return the JSONL destination path."""
        return self._path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self._path.parent, 0o700)
            with self._locked():
                self._compact_unlocked(self._clock())
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(self.format(record))
                    handle.write("\n")
                os.chmod(self._path, 0o600)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._stop.set()
        cleanup_thread = getattr(self, "_cleanup_thread", None)
        if cleanup_thread is not None and cleanup_thread is not threading.current_thread():
            cleanup_thread.join(timeout=1.0)
        super().close()

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(self._cleanup_interval_seconds):
            self._compact(self._clock())

    def _compact(self, now: datetime) -> None:
        if not self._path.is_file():
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._locked():
                self._compact_unlocked(now)
        except OSError:
            return

    def _locked(self) -> Any:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._lock_path.open("a+", encoding="utf-8")
        os.chmod(self._lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return lock

    def _compact_unlocked(self, now: datetime) -> None:
        if not self._path.is_file():
            return
        cutoff = now.astimezone(UTC) - self._retention
        retained: list[str] = []
        with self._path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                timestamp = _jsonl_timestamp(line)
                if timestamp is not None and timestamp >= cutoff:
                    retained.append(line.rstrip("\n") + "\n")

        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        temporary.write_text("".join(retained), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self._path)


def _jsonl_timestamp(line: str) -> datetime | None:
    try:
        payload = json.loads(line)
        raw = payload.get("timestamp") if isinstance(payload, dict) else None
        if not isinstance(raw, str):
            return None
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
    except (ValueError, json.JSONDecodeError):
        return None


def configure_logging(
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
    warning_log_path: Path | None = None,
    warning_retention: timedelta = _DEFAULT_WARNING_RETENTION,
) -> None:
    """Wire the root logger to emit JSON on ``stream`` (default: stdout).

    Idempotent: repeated calls replace the previous handler, they do not
    stack. That matters because a fork's entry point may call the
    composition root more than once.

    On first install this also removes any `logging.basicConfig`-style
    :class:`logging.StreamHandler` that lives on the root logger without
    our marker. That plain-text handler is typically installed by the
    process entry point *before* the composition root runs; leaving it
    behind would double every log line (once plain, once JSON) because
    root-attached handlers all fire per record.
    """
    root = logging.getLogger()
    root.setLevel(level)

    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root.removeHandler(existing)
            existing.close()
            continue
        # Cull the classic `basicConfig` StreamHandler so JSON output is
        # not shadowed by a duplicate plain-text line. Anything more
        # exotic (a custom fork handler, a Sentry handler) is preserved.
        if type(existing) is logging.StreamHandler:  # noqa: E721 - exact-type match
            root.removeHandler(existing)

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)

    if warning_log_path is not None:
        warning_handler = RetainedJsonlHandler(
            warning_log_path,
            retention=warning_retention,
        )
        warning_handler.setLevel(logging.WARNING)
        warning_handler.setFormatter(JsonFormatter())
        setattr(warning_handler, _HANDLER_MARKER, True)
        root.addHandler(warning_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger with the JSON formatter already attached."""
    return logging.getLogger(name)


def log_extra(**fields: Any) -> Mapping[str, Any]:
    """Small helper so callers write ``logger.info(msg, extra=log_extra(k=v))``.

    Not strictly required - plain ``dict`` works - but keeps call sites
    grep-friendly.
    """
    return dict(fields)


__all__ = [
    "JsonFormatter",
    "RetainedJsonlHandler",
    "configure_logging",
    "get_logger",
    "log_extra",
]
