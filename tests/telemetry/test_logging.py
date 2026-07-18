"""JSON structured logging with correlation-id auto-injection."""

from __future__ import annotations

import io
import json
import logging
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.shared.telemetry import (
    configure_logging,
    get_logger,
    log_extra,
    with_correlation,
)
from fdai.shared.telemetry.logging import JsonFormatter, RetainedJsonlHandler


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
