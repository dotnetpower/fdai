#!/usr/bin/env python3
"""Validate a replayable S1-S14 scenario evidence ledger."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

SCENARIO_IDS = tuple(f"S{index}" for index in range(1, 15))
VERDICTS = ("passed", "partial", "blocked", "failed", "not-applicable")
RECOVERY_STATUSES = ("verified", "not-run", "not-applicable")


def _mapping(value: object, field: str, errors: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{field} MUST be an object")
        return None
    return value


def _nonempty_text(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} MUST be non-empty text")


def _utc_timestamp(value: object, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{field} MUST be an RFC 3339 UTC timestamp ending in Z")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} MUST be a valid RFC 3339 UTC timestamp")
        return None
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        errors.append(f"{field} MUST use UTC")
        return None
    return parsed


def _validate_measurements(value: object, scenario_id: str, errors: list[str]) -> None:
    field = f"scenarios.{scenario_id}.measurements"
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        errors.append(f"{field} MUST contain at least one observed measurement")
        return
    for index, measurement_value in enumerate(value):
        measurement = _mapping(measurement_value, f"{field}[{index}]", errors)
        if measurement is None:
            continue
        for key in ("name", "value", "unit", "source"):
            item = measurement.get(key)
            if key == "value":
                if not isinstance(item, (int, float, str)) or isinstance(item, bool):
                    errors.append(f"{field}[{index}].value MUST be numeric or non-empty text")
                elif isinstance(item, str) and not item.strip():
                    errors.append(f"{field}[{index}].value MUST be numeric or non-empty text")
            else:
                _nonempty_text(item, f"{field}[{index}].{key}", errors)
        _utc_timestamp(measurement.get("observed_at"), f"{field}[{index}].observed_at", errors)


def _validate_scenario(scenario_id: str, value: object, errors: list[str]) -> str | None:
    field = f"scenarios.{scenario_id}"
    scenario = _mapping(value, field, errors)
    if scenario is None:
        return None

    status = scenario.get("status")
    if status not in VERDICTS:
        errors.append(f"{field}.status MUST be one of: {', '.join(VERDICTS)}")
        status = None
    _nonempty_text(scenario.get("target"), f"{field}.target", errors)

    window = _mapping(scenario.get("time_window"), f"{field}.time_window", errors)
    if window is not None:
        start = _utc_timestamp(window.get("start"), f"{field}.time_window.start", errors)
        end = _utc_timestamp(window.get("end"), f"{field}.time_window.end", errors)
        if start is not None and end is not None and end < start:
            errors.append(f"{field}.time_window.end MUST not precede start")

    for evidence_name in ("injection_evidence", "detection_evidence", "root_cause"):
        evidence = _mapping(scenario.get(evidence_name), f"{field}.{evidence_name}", errors)
        if evidence is not None:
            _nonempty_text(evidence.get("summary"), f"{field}.{evidence_name}.summary", errors)
            _nonempty_text(evidence.get("source"), f"{field}.{evidence_name}.source", errors)

    _validate_measurements(scenario.get("measurements"), scenario_id, errors)

    recovery = _mapping(scenario.get("recovery_evidence"), f"{field}.recovery_evidence", errors)
    if recovery is not None:
        recovery_status = recovery.get("status")
        if recovery_status not in RECOVERY_STATUSES:
            errors.append(
                f"{field}.recovery_evidence.status MUST be one of: {', '.join(RECOVERY_STATUSES)}"
            )
        _nonempty_text(recovery.get("summary"), f"{field}.recovery_evidence.summary", errors)
        _nonempty_text(recovery.get("source"), f"{field}.recovery_evidence.source", errors)
        if status == "passed" and recovery_status not in ("verified", "not-applicable"):
            errors.append(f"{field} MUST NOT be passed without terminal recovery evidence")

    safety = _mapping(scenario.get("safety"), f"{field}.safety", errors)
    if safety is not None:
        for key in ("approval", "blast_radius", "stop_condition", "rollback"):
            _nonempty_text(safety.get(key), f"{field}.safety.{key}", errors)

    cleanup = _mapping(scenario.get("cleanup"), f"{field}.cleanup", errors)
    if cleanup is not None:
        cleanup_status = cleanup.get("status")
        if cleanup_status not in ("verified", "not-applicable"):
            errors.append(f"{field}.cleanup.status MUST be verified or not-applicable")
        residuals = cleanup.get("residuals")
        if not isinstance(residuals, list):
            errors.append(f"{field}.cleanup.residuals MUST be an array")
        elif residuals:
            errors.append(f"{field}.cleanup.residuals MUST be empty")

    claims = scenario.get("unsupported_claims")
    if not isinstance(claims, list):
        errors.append(f"{field}.unsupported_claims MUST be an array")
    elif claims:
        errors.append(f"{field}.unsupported_claims MUST be empty")
    return status if isinstance(status, str) else None


def validate(payload: object) -> list[str]:
    """Return every evidence-contract violation in deterministic order."""
    errors: list[str] = []
    root = _mapping(payload, "root", errors)
    if root is None:
        return errors
    if root.get("schema_version") != 1:
        errors.append("schema_version MUST equal 1")
    _utc_timestamp(root.get("generated_at"), "generated_at", errors)

    scenarios = _mapping(root.get("scenarios"), "scenarios", errors)
    observed_counts = {verdict: 0 for verdict in VERDICTS}
    if scenarios is not None:
        scenario_keys = set(scenarios)
        expected_keys = set(SCENARIO_IDS)
        for missing in sorted(expected_keys - scenario_keys):
            errors.append(f"scenarios missing {missing}")
        for unexpected in sorted(scenario_keys - expected_keys):
            errors.append(f"scenarios contains unexpected id: {unexpected}")
        for scenario_id in SCENARIO_IDS:
            if scenario_id in scenarios:
                status = _validate_scenario(scenario_id, scenarios[scenario_id], errors)
                if status in observed_counts:
                    observed_counts[status] += 1

    summary = _mapping(root.get("summary"), "summary", errors)
    if summary is not None:
        if set(summary) != set(VERDICTS):
            errors.append(f"summary MUST contain exactly: {', '.join(VERDICTS)}")
        for verdict in VERDICTS:
            if summary.get(verdict) != observed_counts[verdict]:
                errors.append(
                    f"summary.{verdict} MUST equal observed scenario count "
                    f"{observed_counts[verdict]}"
                )
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"sre-evidence: ERROR: cannot read ledger: {exc}", file=sys.stderr)
        return 1
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"sre-evidence: ERROR: {error}", file=sys.stderr)
        return 1
    print("sre-evidence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
