#!/usr/bin/env python3
"""Reduce content-free ChatOps latency samples into five-stage SLO evidence."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "services/core-control-plane/src"))

from fdai.core.conversation_assurance.quality_latency import (
    LatencyBenchmarkBatch,
    LatencyEnvironment,
    LatencySample,
    LatencySampleOutcome,
    LatencyStage,
    reduce_latency_benchmark,
)

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "source_revision",
        "started_at",
        "completed_at",
        "samples",
    }
)
_SAMPLE_KEYS = frozenset(
    {
        "stage",
        "environment",
        "observed_at",
        "duration_ms",
        "timestamp_authority",
        "trace_digest",
        "provenance_digest",
        "outcome",
    }
)


def load_batch(path: Path) -> LatencyBenchmarkBatch:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("latency benchmark input is unreadable") from exc
    return parse_batch(raw)


def parse_batch(raw: object) -> LatencyBenchmarkBatch:
    root = _mapping(raw, "latency benchmark")
    _exact_keys(root, _ROOT_KEYS, "latency benchmark")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise ValueError("latency benchmark schema_version MUST be 1")
    samples = _array(root["samples"], "samples")
    return LatencyBenchmarkBatch(
        run_id=_string(root["run_id"], "run_id"),
        source_revision=_string(root["source_revision"], "source_revision"),
        started_at=_string(root["started_at"], "started_at"),
        completed_at=_string(root["completed_at"], "completed_at"),
        samples=tuple(_sample(value, index) for index, value in enumerate(samples)),
    )


def _sample(raw: object, index: int) -> LatencySample:
    field = f"samples[{index}]"
    value = _mapping(raw, field)
    _exact_keys(value, _SAMPLE_KEYS, field)
    return LatencySample(
        stage=_enum(LatencyStage, value["stage"], f"{field}.stage"),
        environment=_enum(
            LatencyEnvironment,
            value["environment"],
            f"{field}.environment",
        ),
        observed_at=_string(value["observed_at"], f"{field}.observed_at"),
        duration_ms=_number(value["duration_ms"], f"{field}.duration_ms"),
        timestamp_authority=_string(
            value["timestamp_authority"],
            f"{field}.timestamp_authority",
        ),
        trace_digest=_string(value["trace_digest"], f"{field}.trace_digest"),
        provenance_digest=_string(
            value["provenance_digest"],
            f"{field}.provenance_digest",
        ),
        outcome=_enum(
            LatencySampleOutcome,
            value["outcome"],
            f"{field}.outcome",
        ),
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{field} MUST be an object with string keys")
    return raw


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("latency benchmark contains a duplicate object key")
        value[key] = item
    return value


def _reject_json_constant(_: str) -> object:
    raise ValueError("latency benchmark contains a non-finite number")


def _array(raw: object, field: str) -> list[object]:
    if not isinstance(raw, list):
        raise ValueError(f"{field} MUST be an array")
    return raw


def _exact_keys(raw: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    if frozenset(raw) != expected:
        raise ValueError(f"{field} fields differ from the latency benchmark schema")


def _string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{field} MUST be a string")
    return raw


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{field} MUST be an integer")
    return raw


def _number(raw: object, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{field} MUST be a number")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{field} MUST be finite")
    return value


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
    parser.add_argument("--require-slo", action="store_true")
    args = parser.parse_args(argv)
    try:
        evidence = reduce_latency_benchmark(load_batch(args.input))
    except ValueError as exc:
        print(f"chatops-quality-latency: FAIL {exc}", file=sys.stderr)
        return 1
    payload = evidence.to_dict()
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    if args.require_slo and not evidence.latency_slo_met:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
