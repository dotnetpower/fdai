"""Import bounded enforce-run reports into the durable report signal feed."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult
from fdai.core.report_feed.adapters import signal_from_experiment
from fdai.core.report_feed.models import ReportSignal
from fdai.delivery.persistence.postgres_report_signal import (
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
)
from fdai.shared.contracts.models import Mode

_MAX_REPORT_BYTES = 1_048_576
_REQUIRED_RESULT_FIELDS = frozenset(
    {
        "approval_ref",
        "detected",
        "elapsed_seconds",
        "ended_at",
        "error",
        "expected_signal",
        "experiment_id",
        "injected",
        "mode",
        "outcome",
        "reverted",
        "scenario_id",
        "started_at",
        "stop_reason",
        "stopped",
        "targets",
    }
)


def load_enforce_report(path: Path) -> tuple[ReportSignal, ...]:
    """Decode one complete report without trusting display text or local paths."""

    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError("enforce report must be a regular non-symlink file")
    size = resolved.stat().st_size
    if size < 2 or size > _MAX_REPORT_BYTES:
        raise ValueError("enforce report size is outside the supported bound")
    payload = json.loads(
        resolved.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
    )
    root = _mapping(payload, "enforce report")
    if set(root) != {"runs"}:
        raise ValueError("enforce report must contain only runs")
    runs = root["runs"]
    if not isinstance(runs, list) or len(runs) > 256:
        raise ValueError("enforce report runs must be a bounded array")
    return tuple(_signal_from_record(_mapping(run, "enforce report run")) for run in runs)


async def import_enforce_report(path: Path, *, dsn: str) -> int:
    """Idempotently retain every decoded signal and return the decoded count."""

    signals = load_enforce_report(path)
    store = PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn))
    await store.record_many(signals)
    return len(signals)


def _signal_from_record(record: Mapping[str, Any]) -> ReportSignal:
    if set(record) != _REQUIRED_RESULT_FIELDS:
        raise ValueError("enforce report run fields do not match the supported contract")
    result = ExperimentResult(
        experiment_id=_text(record, "experiment_id"),
        scenario_id=_text(record, "scenario_id"),
        mode=Mode(_text(record, "mode")),
        targets=_text_tuple(record, "targets"),
        outcome=ExperimentOutcome(_text(record, "outcome")),
        expected_signal=_text(record, "expected_signal"),
        detected=_boolean(record, "detected"),
        started_at=_timestamp(record, "started_at"),
        ended_at=_timestamp(record, "ended_at"),
        injected=_boolean(record, "injected"),
        stopped=_boolean(record, "stopped"),
        error=_optional_text(record, "error"),
        stop_reason=_optional_text(record, "stop_reason"),
    )
    if result.ended_at < result.started_at:
        raise ValueError("enforce report run timestamps are reversed")
    if _boolean(record, "reverted") is not result.reverted:
        raise ValueError("enforce report reverted value conflicts with the result")
    elapsed = record["elapsed_seconds"]
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
        raise ValueError("enforce report elapsed_seconds must be non-negative")
    approval_ref = _text(record, "approval_ref")
    if len(approval_ref) > 256:
        raise ValueError("enforce report approval_ref exceeds the supported bound")
    signal = signal_from_experiment(result)
    return dataclasses.replace(
        signal,
        metadata={**signal.metadata, "approval_ref": approval_ref},
    )


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"enforce report {key} must be bounded text")
    return value


def _optional_text(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2_048:
        raise ValueError(f"enforce report {key} must be bounded text or null")
    return value


def _boolean(record: Mapping[str, Any], key: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"enforce report {key} must be boolean")
    return value


def _text_tuple(record: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = record.get(key)
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(f"enforce report {key} must be a bounded array")
    if any(not isinstance(item, str) or not item or len(item) > 512 for item in value):
        raise ValueError(f"enforce report {key} must contain bounded text")
    return tuple(value)


def _timestamp(record: Mapping[str, Any], key: str) -> datetime:
    value = _text(record, key)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"enforce report {key} must be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"enforce report {key} must include a UTC offset")
    return parsed


async def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    arguments = parser.parse_args(argv)
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        parser.error("FDAI_STATE_STORE_DSN is required")
    count = await import_enforce_report(arguments.report, dsn=dsn)
    print(json.dumps({"imported": count, "synthetic": False}, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["import_enforce_report", "load_enforce_report", "main"]
