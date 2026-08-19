"""JSON structured logging with correlation-id auto-injection."""

from __future__ import annotations

import io
import json
import logging
import multiprocessing
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.shared.telemetry import (
    configure_logging,
    get_logger,
    log_extra,
    with_correlation,
)
from fdai.shared.telemetry.logging import (
    JsonFormatter,
    RetainedJsonlHandler,
    _BurstSummaryFilter,
)


def _write_warning_records(path: str, worker_id: int, count: int) -> None:
    handler = RetainedJsonlHandler(Path(path), cleanup_interval_seconds=3600)
    handler.setFormatter(JsonFormatter())
    try:
        for record_index in range(count):
            record = logging.LogRecord(
                "fdai.tests.concurrent",
                logging.WARNING,
                "",
                0,
                "concurrent warning",
                (),
                None,
            )
            record.worker_id = worker_id
            record.record_index = record_index
            handler.emit(record)
    finally:
        handler.close()


@pytest.fixture()
def json_stream() -> io.StringIO:
    """A stream + logger config isolated to this test."""
    stream = io.StringIO()
    configure_logging(level=logging.DEBUG, stream=stream)
    return stream


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    stream.seek(0)
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_log_line_is_json_with_required_keys(json_stream: io.StringIO) -> None:
    logger = get_logger("fdai.tests.telemetry")
    logger.info("hello world")

    lines = _lines(json_stream)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["level"] == "INFO"
    assert entry["logger"] == "fdai.tests.telemetry"
    assert entry["message"] == "hello world"
    assert entry["correlation_id"] is None
    # ISO 8601 UTC - 'T' separator, ends with '+00:00' or 'Z'.
    ts = str(entry["timestamp"])
    assert "T" in ts and (ts.endswith("+00:00") or ts.endswith("Z"))


def test_correlation_id_flows_into_log_line(json_stream: io.StringIO) -> None:
    logger = get_logger("fdai.tests.telemetry")
    with with_correlation("evt-42"):
        logger.info("processing")
    lines = _lines(json_stream)
    assert lines[0]["correlation_id"] == "evt-42"


def test_extra_fields_survive_serialization(json_stream: io.StringIO) -> None:
    logger = get_logger("fdai.tests.telemetry")
    logger.info("with extra", extra=log_extra(tier="t0", decision="auto"))
    lines = _lines(json_stream)
    assert lines[0]["tier"] == "t0"
    assert lines[0]["decision"] == "auto"


def test_configure_logging_is_idempotent(json_stream: io.StringIO) -> None:
    # Reconfigure with a fresh stream - the old handler is replaced,
    # not stacked. Two calls MUST NOT double-emit.
    second = io.StringIO()
    configure_logging(level=logging.DEBUG, stream=second)

    logger = get_logger("fdai.tests.telemetry")
    logger.info("second stream only")

    # First stream got nothing after reconfig.
    first_lines = _lines(json_stream)
    second_lines = _lines(second)
    assert len(second_lines) == 1
    assert not any(line.get("message") == "second stream only" for line in first_lines)


def test_logger_exception_serializes_traceback_into_exception_field(
    json_stream: io.StringIO,
) -> None:
    """`logger.exception(...)` MUST render the traceback under the top-level
    ``exception`` key, not swallow it or crash the formatter.
    """
    logger = get_logger("fdai.tests.telemetry")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("wrapped failure")

    lines = _lines(json_stream)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["message"] == "wrapped failure"
    assert entry["level"] == "ERROR"
    assert "exception" in entry
    exc_text = str(entry["exception"])
    assert "RuntimeError" in exc_text
    assert "boom" in exc_text


def test_json_formatter_bounds_oversized_records_as_valid_json() -> None:
    record = logging.LogRecord(
        "fdai.tests.large",
        logging.WARNING,
        "",
        0,
        "가" * 100_000,
        (),
        None,
    )
    record.unbounded_context = "y" * 100_000

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)

    assert len(rendered.encode("utf-8")) <= 65_536
    assert payload["log_record_truncated"] is True
    assert payload["original_bytes"] > 65_536
    assert str(payload["message"]).endswith("...[truncated]")
    assert "unbounded_context" not in payload


def test_json_formatter_bounds_all_preserved_context_and_exception() -> None:
    try:
        raise RuntimeError("나" * 100_000)
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "fdai.tests.large",
        logging.WARNING,
        "",
        0,
        "가" * 100_000,
        (),
        exc_info,
    )
    for field in (
        "agent",
        "error_type",
        "phase",
        "state",
        "topic",
    ):
        setattr(record, field, "한" * 10_000)
    record.failure_count = 10_000
    record.suppressed_count = 10_000
    record.suppression_window_seconds = 10.0

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)

    assert len(rendered.encode("utf-8")) <= 65_536
    assert payload["log_record_truncated"] is True
    assert str(payload["message"]).endswith("...[truncated]")
    assert str(payload["exception"]).endswith("...[truncated]")


def test_json_formatter_rechecks_total_after_context_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_fields = tuple(f"context_{index}" for index in range(200))
    monkeypatch.setattr(
        "fdai.shared.telemetry.logging._TRUNCATED_CONTEXT_FIELDS",
        context_fields,
    )
    record = logging.LogRecord(
        "fdai.tests.large",
        logging.WARNING,
        "",
        0,
        "가" * 100_000,
        (),
        None,
    )
    for field in context_fields:
        setattr(record, field, "한" * 10_000)

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)

    assert len(rendered.encode("utf-8")) <= 65_536
    assert payload["context_truncated"] is True
    assert "context_0" not in payload


def test_warning_file_records_warning_and_error_only(tmp_path: Path) -> None:
    stream = io.StringIO()
    warning_path = tmp_path / ".fdai/logs/warnings.jsonl"
    configure_logging(
        level=logging.DEBUG,
        stream=stream,
        warning_log_path=warning_path,
    )
    logger = get_logger("fdai.tests.warning-file")

    logger.info("not persisted")
    logger.warning("warning persisted")
    logger.error("error persisted")

    entries = [json.loads(line) for line in warning_path.read_text().splitlines()]
    assert [entry["level"] for entry in entries] == ["WARNING", "ERROR"]
    assert stat.S_IMODE(warning_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(warning_path.parent.stat().st_mode) == 0o700
    configure_logging(level=logging.DEBUG, stream=io.StringIO())


def test_warning_file_retains_only_last_24_hours(tmp_path: Path) -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    warning_path = tmp_path / "warnings.jsonl"
    warning_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "timestamp": (cutoff - timedelta(seconds=1)).isoformat(),
                        "message": "expired",
                    }
                ),
                json.dumps({"timestamp": cutoff.isoformat(), "message": "boundary"}),
                json.dumps(
                    {
                        "timestamp": (now - timedelta(hours=1)).isoformat(),
                        "message": "fresh",
                    }
                ),
                "not-json",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    handler = RetainedJsonlHandler(
        warning_path,
        retention=timedelta(hours=24),
        cleanup_interval_seconds=3600,
        clock=lambda: now,
    )
    handler.setFormatter(JsonFormatter())
    handler.close()

    entries = [json.loads(line) for line in warning_path.read_text().splitlines()]
    assert [entry["message"] for entry in entries] == ["boundary", "fresh"]


def test_warning_file_does_not_compact_before_each_emit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning_path = tmp_path / "warnings.jsonl"
    handler = RetainedJsonlHandler(
        warning_path,
        cleanup_interval_seconds=3600,
    )
    handler.setFormatter(JsonFormatter())
    compact_calls = 0
    original_compact = handler._compact_unlocked

    def record_compaction(now: datetime) -> None:
        nonlocal compact_calls
        compact_calls += 1
        original_compact(now)

    monkeypatch.setattr(handler, "_compact_unlocked", record_compaction)
    try:
        handler.emit(logging.LogRecord("test", logging.WARNING, "", 0, "one", (), None))
        handler.emit(logging.LogRecord("test", logging.ERROR, "", 0, "two", (), None))
    finally:
        handler.close()

    assert compact_calls == 0
    entries = [json.loads(line) for line in warning_path.read_text().splitlines()]
    assert [entry["message"] for entry in entries] == ["one", "two"]


def test_warning_file_compacts_once_per_shared_cleanup_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 19, 0, 0, tzinfo=UTC)
    warning_path = tmp_path / "warnings.jsonl"
    handler = RetainedJsonlHandler(
        warning_path,
        cleanup_interval_seconds=300,
        clock=lambda: now,
    )
    compact_calls = 0
    original_compact = handler._compact_unlocked

    def record_compaction(compaction_time: datetime) -> None:
        nonlocal compact_calls
        compact_calls += 1
        original_compact(compaction_time)

    monkeypatch.setattr(handler, "_compact_unlocked", record_compaction)
    try:
        handler._compact(now + timedelta(seconds=299))
        handler._compact(now + timedelta(seconds=300))
    finally:
        handler.close()

    assert compact_calls == 1


def test_warning_file_lock_timeout_does_not_escape_emit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning_path = tmp_path / "warnings.jsonl"
    handler = RetainedJsonlHandler(warning_path, cleanup_interval_seconds=3600)
    errors: list[logging.LogRecord] = []
    clock_values = iter((0.0, 1.0))
    monkeypatch.setattr(
        "fdai.shared.telemetry.logging.time.monotonic",
        lambda: next(clock_values),
    )
    monkeypatch.setattr(
        "fdai.shared.telemetry.logging.fcntl.flock",
        lambda *_args: (_ for _ in ()).throw(BlockingIOError()),
    )
    monkeypatch.setattr(handler, "handleError", errors.append)
    record = logging.LogRecord("test", logging.WARNING, "", 0, "blocked", (), None)
    try:
        handler.emit(record)
    finally:
        handler.close()

    assert errors == [record]


def test_warning_file_preserves_concurrent_process_records(tmp_path: Path) -> None:
    warning_path = tmp_path / "warnings.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_write_warning_records, args=(str(warning_path), worker_id, 50))
        for worker_id in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0, 0, 0]
    entries = [json.loads(line) for line in warning_path.read_text().splitlines()]
    identities = {(entry["worker_id"], entry["record_index"]) for entry in entries}
    assert len(entries) == 200
    assert len(identities) == 200


def test_burst_filter_preserves_first_and_periodic_dependency_evidence() -> None:
    now = 0.0
    burst_filter = _BurstSummaryFilter(interval_seconds=10, clock=lambda: now)

    def dependency_record(error: Exception) -> logging.LogRecord:
        return logging.LogRecord(
            "aiokafka.consumer.fetcher",
            logging.ERROR,
            "",
            0,
            "Failed fetch messages from %s: %s",
            (1, error),
            None,
        )

    first = dependency_record(RuntimeError("same"))
    assert burst_filter.filter(first) is True
    assert burst_filter.filter(first) is True
    assert burst_filter.filter(dependency_record(RuntimeError("same"))) is False

    now = 10.0
    periodic = dependency_record(RuntimeError("same"))
    assert burst_filter.filter(periodic) is True
    assert periodic.suppressed_count == 1
    assert periodic.suppression_window_seconds == 10


def test_burst_filter_never_merges_distinct_error_types() -> None:
    burst_filter = _BurstSummaryFilter(interval_seconds=10, clock=lambda: 0)
    runtime_error = logging.LogRecord(
        "aiokafka",
        logging.ERROR,
        "",
        0,
        "dependency failed: %s",
        (RuntimeError("runtime"),),
        None,
    )
    value_error = logging.LogRecord(
        "aiokafka",
        logging.ERROR,
        "",
        0,
        "dependency failed: %s",
        (ValueError("value"),),
        None,
    )

    assert burst_filter.filter(runtime_error) is True
    assert burst_filter.filter(value_error) is True


def test_burst_filter_never_merges_distinct_dependency_messages() -> None:
    burst_filter = _BurstSummaryFilter(interval_seconds=10, clock=lambda: 0)
    first = logging.LogRecord(
        "aiokafka.consumer.fetcher",
        logging.ERROR,
        "",
        0,
        "Failed fetch messages from %s: %s",
        (1, RuntimeError("first")),
        None,
    )
    second = logging.LogRecord(
        "aiokafka.consumer.fetcher",
        logging.ERROR,
        "",
        0,
        "Failed fetch messages from %s: %s",
        (2, RuntimeError("second")),
        None,
    )

    assert burst_filter.filter(first) is True
    assert burst_filter.filter(second) is True


def test_configured_handlers_share_burst_decisions_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    stream = io.StringIO()
    warning_path = tmp_path / "warnings.jsonl"
    monkeypatch.setattr(
        "fdai.shared.telemetry.logging.time.monotonic",
        lambda: now,
    )
    configure_logging(
        level=logging.INFO,
        stream=stream,
        warning_log_path=warning_path,
    )
    logger = get_logger("aiokafka.consumer.fetcher")
    try:
        logger.error("Failed fetch messages from %s: %s", 1, RuntimeError("same"))
        logger.error("Failed fetch messages from %s: %s", 1, RuntimeError("same"))
        now = 10.0
        logger.error("Failed fetch messages from %s: %s", 1, RuntimeError("same"))
    finally:
        configure_logging(level=logging.INFO, stream=io.StringIO())

    stream_entries = _lines(stream)
    file_entries = [json.loads(line) for line in warning_path.read_text().splitlines()]
    assert len(stream_entries) == 2
    assert len(file_entries) == 2
    assert stream_entries == file_entries
    assert stream_entries[-1]["suppressed_count"] == 1
    assert stream_entries[-1]["suppression_window_seconds"] == 10.0
