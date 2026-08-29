#!/usr/bin/env python3
"""Reduce content-free ChatOps record commitments into complete trace evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "services/core-control-plane/src"))

from fdai.core.conversation_assurance.quality_trace import (
    CorrelationTraceBatch,
    CorrelationTraceEvent,
    CorrelationTraceStage,
    TraceTimestampAuthority,
    reduce_correlation_trace,
)

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "trace_id",
        "source_revision",
        "started_at",
        "completed_at",
        "events",
    }
)
_EVENT_KEYS = frozenset(
    {
        "stage",
        "occurred_at",
        "timestamp_authority",
        "correlation_digest",
        "record_digest",
        "predecessor_record_digest",
        "provenance_digest",
    }
)


def load_batch(path: Path) -> CorrelationTraceBatch:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("correlation trace input is unreadable") from exc
    return parse_batch(raw)


def parse_batch(raw: object) -> CorrelationTraceBatch:
    root = _mapping(raw, "correlation trace")
    _exact_keys(root, _ROOT_KEYS, "correlation trace")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise ValueError("correlation trace schema_version MUST be 1")
    return CorrelationTraceBatch(
        trace_id=_string(root["trace_id"], "trace_id"),
        source_revision=_string(root["source_revision"], "source_revision"),
        started_at=_string(root["started_at"], "started_at"),
        completed_at=_string(root["completed_at"], "completed_at"),
        events=tuple(
            _event(value, index) for index, value in enumerate(_array(root["events"], "events"))
        ),
    )


def _event(raw: object, index: int) -> CorrelationTraceEvent:
    field = f"events[{index}]"
    value = _mapping(raw, field)
    _exact_keys(value, _EVENT_KEYS, field)
    predecessor = value["predecessor_record_digest"]
    if predecessor is not None and not isinstance(predecessor, str):
        raise ValueError(f"{field}.predecessor_record_digest MUST be a string or null")
    return CorrelationTraceEvent(
        stage=_enum(CorrelationTraceStage, value["stage"], f"{field}.stage"),
        occurred_at=_string(value["occurred_at"], f"{field}.occurred_at"),
        timestamp_authority=_enum(
            TraceTimestampAuthority,
            value["timestamp_authority"],
            f"{field}.timestamp_authority",
        ),
        correlation_digest=_string(
            value["correlation_digest"],
            f"{field}.correlation_digest",
        ),
        record_digest=_string(value["record_digest"], f"{field}.record_digest"),
        predecessor_record_digest=predecessor,
        provenance_digest=_string(
            value["provenance_digest"],
            f"{field}.provenance_digest",
        ),
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{field} MUST be an object with string keys")
    return raw


def _array(raw: object, field: str) -> list[object]:
    if not isinstance(raw, list):
        raise ValueError(f"{field} MUST be an array")
    return raw


def _exact_keys(raw: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    if frozenset(raw) != expected:
        raise ValueError(f"{field} fields differ from the correlation trace schema")


def _string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{field} MUST be a string")
    return raw


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{field} MUST be an integer")
    return raw


def _enum[EnumT: StrEnum](
    enum_type: type[EnumT],
    raw: object,
    field: str,
) -> EnumT:
    try:
        return enum_type(_string(raw, field))
    except ValueError as exc:
        raise ValueError(f"{field} contains an unsupported value") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        evidence = reduce_correlation_trace(load_batch(args.input))
    except ValueError as exc:
        print(f"chatops-quality-trace: FAIL {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(evidence.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    if args.require_complete and not evidence.complete_trace:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
