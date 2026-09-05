#!/usr/bin/env python3
"""Validate and summarize content-free governed document lifecycle evidence."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

_REQUIRED_SERVICES = frozenset(
    {
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        "operator-service",
    }
)
_REQUIRED_STAGES = frozenset(
    {
        "upload",
        "scan",
        "protection_inspection",
        "extraction",
        "indexing",
        "citation",
        "deletion",
        "restart",
        "provider_failure",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "content",
        "document_text",
        "filename",
        "preview",
        "source_name",
        "source_url",
        "text",
    }
)


class DocumentEvidenceError(ValueError):
    """The evidence cannot support a governed document baseline."""


def summarize_evidence(payload: Mapping[str, object]) -> dict[str, object]:
    _reject_content_fields(payload)
    if payload.get("schema_version") != "1.0.0":
        raise DocumentEvidenceError("schema_version MUST be 1.0.0")
    if payload.get("corpus_reviewed") is not True:
        raise DocumentEvidenceError("the corpus MUST have an independent review")
    if payload.get("contains_sensitive_data") is not False:
        raise DocumentEvidenceError("the baseline corpus MUST be non-sensitive")
    revision = _required_string(payload, "revision")
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise DocumentEvidenceError("revision MUST be a lowercase 40-character git SHA")
    services = payload.get("services")
    if (
        not isinstance(services, list)
        or not all(isinstance(service, str) for service in services)
        or frozenset(services) != _REQUIRED_SERVICES
        or len(services) != len(_REQUIRED_SERVICES)
    ):
        raise DocumentEvidenceError("services MUST contain the exact five-service topology")
    window_seconds = _nonnegative_number(payload, "window_seconds")
    if window_seconds <= 0:
        raise DocumentEvidenceError("window_seconds MUST be positive")
    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        raise DocumentEvidenceError("observations MUST be a non-empty array")

    by_stage: dict[str, list[float]] = {}
    queue_delays: list[float] = []
    storage_values: list[int] = []
    failures = 0
    successful_documents: set[str] = set()
    for raw in observations:
        if not isinstance(raw, dict):
            raise DocumentEvidenceError("each observation MUST be an object")
        stage = _required_string(raw, "stage")
        if stage not in _REQUIRED_STAGES:
            raise DocumentEvidenceError(f"unsupported document evidence stage: {stage}")
        latency = _nonnegative_number(raw, "latency_ms")
        queue_delay = _nonnegative_number(raw, "queue_delay_ms")
        storage_bytes = _nonnegative_integer(raw, "storage_bytes")
        outcome = _required_string(raw, "outcome")
        if outcome not in {"success", "failure"}:
            raise DocumentEvidenceError("observation outcome MUST be success or failure")
        document_ref = _required_string(raw, "document_ref")
        if len(document_ref) > 256:
            raise DocumentEvidenceError("document_ref exceeds the configured bound")
        by_stage.setdefault(stage, []).append(latency)
        queue_delays.append(queue_delay)
        storage_values.append(storage_bytes)
        if outcome == "failure":
            failures += 1
        elif stage == "citation":
            successful_documents.add(document_ref)

    missing = sorted(_REQUIRED_STAGES.difference(by_stage))
    if missing:
        raise DocumentEvidenceError("receipt is missing stages: " + ", ".join(missing))
    if not any(
        raw.get("stage") == "provider_failure" and raw.get("outcome") == "failure"
        for raw in observations
        if isinstance(raw, dict)
    ):
        raise DocumentEvidenceError("provider_failure MUST retain one explicit failure outcome")

    stage_latency = {
        stage: {
            "p50_ms": _nearest_rank(values, 0.50),
            "p95_ms": _nearest_rank(values, 0.95),
            "samples": len(values),
        }
        for stage, values in sorted(by_stage.items())
    }
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "service_count": len(services),
        "observation_count": len(observations),
        "stage_latency": stage_latency,
        "queue_delay": {
            "p50_ms": _nearest_rank(queue_delays, 0.50),
            "p95_ms": _nearest_rank(queue_delays, 0.95),
        },
        "throughput_documents_per_second": len(successful_documents) / window_seconds,
        "storage_growth_bytes": max(storage_values) - min(storage_values),
        "failure_rate": failures / len(observations),
    }


def _reject_content_fields(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise DocumentEvidenceError(f"{path} contains a non-string key")
            if key.casefold() in _FORBIDDEN_KEYS:
                raise DocumentEvidenceError(f"{path}.{key} is not allowed in content-free evidence")
            _reject_content_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_content_fields(nested, f"{path}[{index}]")


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DocumentEvidenceError(f"{key} MUST be a non-empty string")
    return value


def _nonnegative_number(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DocumentEvidenceError(f"{key} MUST be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise DocumentEvidenceError(f"{key} MUST be finite and non-negative")
    return number


def _nonnegative_integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DocumentEvidenceError(f"{key} MUST be a non-negative integer")
    return value


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and summarize a content-free document lifecycle receipt."
    )
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            _fail("receipt root MUST be an object")
        summary = summarize_evidence(raw)
    except (OSError, json.JSONDecodeError, DocumentEvidenceError) as exc:
        _fail(f"document evidence validation failed: {exc}")
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
