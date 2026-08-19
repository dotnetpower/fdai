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
import hashlib
import json
import logging
import os
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Hashable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from .correlation import current_correlation_id

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_MAX_JSON_LOG_BYTES = 65_536
_MAX_TRUNCATED_MESSAGE_BYTES = 32_768
_MAX_TRUNCATED_EXCEPTION_BYTES = 16_384
_MAX_TRUNCATED_CONTEXT_BYTES = 512
_TRUNCATED_CONTEXT_FIELDS = (
    "agent",
    "error_type",
    "failure_count",
    "phase",
    "state",
    "suppressed_count",
    "suppression_window_seconds",
    "topic",
)


def _truncate_json_text(value: str, max_bytes: int) -> str:
    if len(json.dumps(value, ensure_ascii=True).encode("utf-8")) <= max_bytes:
        return value
    suffix = "...[truncated]"
    lower = 0
    upper = len(value)
    while lower < upper:
        midpoint = (lower + upper + 1) // 2
        candidate = value[:midpoint] + suffix
        if len(json.dumps(candidate, ensure_ascii=True).encode("utf-8")) <= max_bytes:
            lower = midpoint
        else:
            upper = midpoint - 1
    return value[:lower] + suffix


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

        rendered = json.dumps(payload, ensure_ascii=True, default=str)
        rendered_bytes = len(rendered.encode("utf-8"))
        if rendered_bytes <= _MAX_JSON_LOG_BYTES:
            return rendered

        bounded: dict[str, Any] = {
            "timestamp": payload["timestamp"],
            "level": payload["level"],
            "logger": _truncate_json_text(str(payload["logger"]), _MAX_TRUNCATED_CONTEXT_BYTES),
            "message": _truncate_json_text(
                str(payload["message"]),
                _MAX_TRUNCATED_MESSAGE_BYTES,
            ),
            "correlation_id": _truncate_json_text(
                str(payload["correlation_id"]),
                _MAX_TRUNCATED_CONTEXT_BYTES,
            )
            if payload["correlation_id"] is not None
            else None,
            "log_record_truncated": True,
            "original_bytes": rendered_bytes,
        }
        exception = payload.get("exception")
        if isinstance(exception, str):
            bounded["exception"] = _truncate_json_text(
                exception,
                _MAX_TRUNCATED_EXCEPTION_BYTES,
            )
        for field in _TRUNCATED_CONTEXT_FIELDS:
            value = payload.get(field)
            if isinstance(value, (bool, int, float)):
                bounded[field] = value
            elif isinstance(value, str):
                bounded[field] = _truncate_json_text(value, _MAX_TRUNCATED_CONTEXT_BYTES)
        bounded_rendered = json.dumps(bounded, ensure_ascii=True, default=str)
        if len(bounded_rendered.encode("utf-8")) <= _MAX_JSON_LOG_BYTES:
            return bounded_rendered

        fallback: dict[str, Any] = {
            "timestamp": payload["timestamp"],
            "level": payload["level"],
            "logger": _truncate_json_text(str(payload["logger"]), 256),
            "message": _truncate_json_text(str(payload["message"]), 8_192),
            "correlation_id": _truncate_json_text(str(payload["correlation_id"]), 256)
            if payload["correlation_id"] is not None
            else None,
            "log_record_truncated": True,
            "original_bytes": rendered_bytes,
            "context_truncated": True,
        }
        if isinstance(exception, str):
            fallback["exception"] = _truncate_json_text(exception, 4_096)
        return json.dumps(fallback, ensure_ascii=True, default=str)


_HANDLER_MARKER = "_fdai_json_handler"
_DEFAULT_WARNING_RETENTION = timedelta(hours=24)
_DEFAULT_CLEANUP_INTERVAL_SECONDS = 300.0
_LOCK_TIMEOUT_SECONDS = 0.25
_LOCK_RETRY_SECONDS = 0.005
_BURST_SUMMARY_INTERVAL_SECONDS = 10.0
_BURST_STATE_CAPACITY = 256
_BURST_DECISION_FIELD = "_fdai_burst_summary_allowed"
_OWNED_BURST_MESSAGES = frozenset(
    {
        "pantheon_consumer_state_observer_failed",
        "pantheon_handler_observer_failed",
    }
)


class _BurstSummaryFilter(logging.Filter):
    """Keep first and periodic evidence for bounded, explicitly noisy log families."""

    def __init__(
        self,
        *,
        interval_seconds: float = _BURST_SUMMARY_INTERVAL_SECONDS,
        capacity: int = _BURST_STATE_CAPACITY,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        if interval_seconds <= 0:
            raise ValueError("burst summary interval MUST be positive")
        if capacity < 1:
            raise ValueError("burst summary capacity MUST be positive")
        self._interval_seconds = interval_seconds
        self._capacity = capacity
        self._clock = clock or time.monotonic
        self._states: OrderedDict[tuple[Hashable, ...], tuple[float, int]] = OrderedDict()
        self._state_lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        existing = getattr(record, _BURST_DECISION_FIELD, None)
        if isinstance(existing, bool):
            return existing
        key = self._key(record)
        if key is None:
            setattr(record, _BURST_DECISION_FIELD, True)
            return True
        now = self._clock()
        with self._state_lock:
            state = self._states.get(key)
            if state is not None and now - state[0] < self._interval_seconds:
                self._states[key] = (state[0], state[1] + 1)
                self._states.move_to_end(key)
                setattr(record, _BURST_DECISION_FIELD, False)
                return False
            if state is not None and state[1] > 0:
                record.suppressed_count = state[1]
                record.suppression_window_seconds = self._interval_seconds
            self._states[key] = (now, 0)
            self._states.move_to_end(key)
            while len(self._states) > self._capacity:
                self._states.popitem(last=False)
        setattr(record, _BURST_DECISION_FIELD, True)
        return True

    @staticmethod
    def _key(record: logging.LogRecord) -> tuple[Hashable, ...] | None:
        message_template = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
        if record.levelno >= logging.WARNING and (
            record.name == "aiokafka" or record.name.startswith("aiokafka.")
        ):
            exception_type = (
                record.exc_info[0].__name__
                if record.exc_info is not None and record.exc_info[0] is not None
                else None
            )
            rendered_digest = hashlib.sha256(record.getMessage().encode("utf-8")).digest()
            return (
                "dependency",
                record.name,
                record.levelno,
                message_template,
                rendered_digest,
                exception_type,
                current_correlation_id(),
            )
        if (
            record.name == "fdai.agents._framework.bus_bridge"
            and message_template in _OWNED_BURST_MESSAGES
        ):
            return (
                "pantheon-observer",
                message_template,
                record.__dict__.get("agent"),
                record.__dict__.get("topic"),
                record.__dict__.get("phase"),
                record.__dict__.get("state"),
                record.__dict__.get("error_type"),
                current_correlation_id(),
            )
        return None


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
        self._prepare_storage()
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
            with self._locked():
                self._append_unlocked(self.format(record) + "\n")
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

    def _prepare_storage(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self._path.parent, 0o700)
        self._path.touch(exist_ok=True)
        os.chmod(self._path, 0o600)
        self._lock_path.touch(exist_ok=True)
        os.chmod(self._lock_path, 0o600)

    def _append_unlocked(self, entry: str) -> None:
        payload = entry.encode("utf-8")
        descriptor = os.open(
            self._path,
            os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC,
        )
        try:
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
        finally:
            os.close(descriptor)

    def _compact(self, now: datetime) -> None:
        try:
            with self._locked() as lock:
                if not self._compaction_due(lock, now):
                    return
                self._compact_unlocked(now)
                self._record_compaction(lock, now)
        except OSError:
            return

    def _compaction_due(self, lock: TextIO, now: datetime) -> bool:
        lock.seek(0)
        raw = lock.read().strip()
        if not raw:
            return True
        try:
            last_compaction = datetime.fromisoformat(raw)
        except ValueError:
            return True
        if last_compaction.tzinfo is None:
            return True
        elapsed = now.astimezone(UTC) - last_compaction.astimezone(UTC)
        return elapsed < timedelta(0) or elapsed.total_seconds() >= self._cleanup_interval_seconds

    @staticmethod
    def _record_compaction(lock: TextIO, now: datetime) -> None:
        lock.seek(0)
        lock.truncate()
        lock.write(now.astimezone(UTC).isoformat())
        lock.flush()

    def _locked(self) -> Any:
        lock = self._lock_path.open("r+", encoding="utf-8")
        try:
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return lock
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"warning log lock timed out after {_LOCK_TIMEOUT_SECONDS} seconds"
                        ) from exc
                    time.sleep(_LOCK_RETRY_SECONDS)
        except Exception:
            lock.close()
            raise

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
    burst_filter = _BurstSummaryFilter()
    handler.addFilter(burst_filter)
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)

    if warning_log_path is not None:
        warning_handler = RetainedJsonlHandler(
            warning_log_path,
            retention=warning_retention,
        )
        warning_handler.setLevel(logging.WARNING)
        warning_handler.setFormatter(JsonFormatter())
        warning_handler.addFilter(burst_filter)
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
