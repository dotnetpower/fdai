"""JSON structured logging with correlation-id auto-injection."""

from __future__ import annotations

import io
import json
import logging

import pytest

from aiopspilot.shared.telemetry import (
    configure_logging,
    get_logger,
    log_extra,
    with_correlation,
)


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
    logger = get_logger("aiopspilot.tests.telemetry")
    logger.info("hello world")

    lines = _lines(json_stream)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["level"] == "INFO"
    assert entry["logger"] == "aiopspilot.tests.telemetry"
    assert entry["message"] == "hello world"
    assert entry["correlation_id"] is None
    # ISO 8601 UTC - 'T' separator, ends with '+00:00' or 'Z'.
    ts = str(entry["timestamp"])
    assert "T" in ts and (ts.endswith("+00:00") or ts.endswith("Z"))


def test_correlation_id_flows_into_log_line(json_stream: io.StringIO) -> None:
    logger = get_logger("aiopspilot.tests.telemetry")
    with with_correlation("evt-42"):
        logger.info("processing")
    lines = _lines(json_stream)
    assert lines[0]["correlation_id"] == "evt-42"


def test_extra_fields_survive_serialization(json_stream: io.StringIO) -> None:
    logger = get_logger("aiopspilot.tests.telemetry")
    logger.info("with extra", extra=log_extra(tier="t0", decision="auto"))
    lines = _lines(json_stream)
    assert lines[0]["tier"] == "t0"
    assert lines[0]["decision"] == "auto"


def test_configure_logging_is_idempotent(json_stream: io.StringIO) -> None:
    # Reconfigure with a fresh stream - the old handler is replaced,
    # not stacked. Two calls MUST NOT double-emit.
    second = io.StringIO()
    configure_logging(level=logging.DEBUG, stream=second)

    logger = get_logger("aiopspilot.tests.telemetry")
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
    logger = get_logger("aiopspilot.tests.telemetry")
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
