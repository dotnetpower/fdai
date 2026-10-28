"""Diagnostic retention is byte-bounded independently of event volume or writer count."""

from __future__ import annotations

import json
import logging
import multiprocessing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.shared.telemetry.logging import JsonFormatter, RetainedJsonlHandler

_CAP = 256 * 1_024


def _warning(index: int, message: str = "bounded warning") -> logging.LogRecord:
    record = logging.LogRecord("test.warning-bounds", logging.WARNING, "", 0, message, (), None)
    record.record_index = index
    return record


def _write_bounded_warnings(path: str, writer: int) -> None:
    handler = RetainedJsonlHandler(Path(path), max_bytes=_CAP)
    handler.setFormatter(JsonFormatter())
    try:
        for index in range(80):
            record = _warning(index, "x" * 8_192)
            record.writer = writer
            handler.emit(record)
    finally:
        handler.close()


def test_warning_file_stays_within_exact_byte_cap_after_every_append(tmp_path: Path) -> None:
    path = tmp_path / "warnings.jsonl"
    handler = RetainedJsonlHandler(path, max_bytes=_CAP)
    handler.setFormatter(JsonFormatter())
    try:
        for index in range(160):
            handler.emit(_warning(index, "활동 경고 " * 512))
            assert path.stat().st_size <= _CAP
    finally:
        handler.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[-1]["record_index"] == 159
    assert any(record.get("log_retention_truncated") is True for record in records)
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("warnings.jsonl.*[0-9]"))
    assert not list(tmp_path.glob("*.tmp"))


def test_oversized_existing_file_is_reclaimed_even_with_a_recent_shared_cleanup(tmp_path: Path):
    path = tmp_path / "warnings.jsonl"
    now = datetime.now(UTC)
    initial = RetainedJsonlHandler(path, max_bytes=_CAP, clock=lambda: now)
    initial.close()
    with path.open("w") as stream:
        for index in range(800):
            stream.write(
                json.dumps(
                    {
                        "timestamp": now.isoformat(),
                        "message": "한글 로그 " * 512,
                        "record_index": index,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    original_bytes = path.stat().st_size
    assert original_bytes > 10 * _CAP

    restarted = RetainedJsonlHandler(
        path,
        max_bytes=_CAP,
        clock=lambda: now,
        cleanup_interval_seconds=3_600,
    )
    restarted.close()

    assert path.stat().st_size <= _CAP // 2
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[-2]["record_index"] == 799
    assert records[-1]["log_retention_truncated"] is True
    assert records[-1]["omitted_prefix_bytes"] >= original_bytes - _CAP // 2


def test_concurrent_writers_share_one_cap_and_keep_complete_json_lines(tmp_path: Path):
    path = tmp_path / "warnings.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_write_bounded_warnings, args=(str(path), writer))
        for writer in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
    assert [process.exitcode for process in processes] == [0, 0, 0]
    assert path.stat().st_size <= _CAP
    records = [json.loads(line) for line in path.read_text().splitlines()]
    identities = [
        (record["writer"], record["record_index"]) for record in records if "writer" in record
    ]
    assert len(identities) == len(set(identities))
    assert any(record.get("log_retention_truncated") for record in records)


@pytest.mark.parametrize("cap", [0, -1, True, 65_536, "4194304"])
def test_invalid_byte_caps_fail_before_storage_creation(tmp_path: Path, cap):
    path = tmp_path / "warnings.jsonl"
    with pytest.raises(ValueError, match="byte cap"):
        RetainedJsonlHandler(path, max_bytes=cap)
    assert not path.exists()


def test_custom_oversized_formatter_is_explicitly_rejected_not_written(tmp_path: Path, monkeypatch):
    path = tmp_path / "warnings.jsonl"
    handler = RetainedJsonlHandler(path, max_bytes=_CAP)
    errors = []
    monkeypatch.setattr(handler, "handleError", errors.append)
    record = _warning(1, "x" * _CAP)
    try:
        handler.emit(record)
    finally:
        handler.close()
    assert errors == [record]
    assert path.stat().st_size <= _CAP
