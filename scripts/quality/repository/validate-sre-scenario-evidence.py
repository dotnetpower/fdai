#!/usr/bin/env python3
"""Validate a replayable S1-S14 scenario evidence ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

SCENARIO_IDS = tuple(f"S{index}" for index in range(1, 15))
VERDICTS = ("passed", "partial", "blocked", "failed", "not-applicable")
RECOVERY_STATUSES = ("verified", "not-run", "not-applicable")
RECEIPT_TEXT_FIELDS = (
    "authority_class",
    "source_identity",
    "scope",
    "purpose",
    "query_version",
    "freshness",
    "completeness",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _validate_evidence_receipt(
    value: object,
    field: str,
    errors: list[str],
) -> Mapping[str, Any] | None:
    receipt = _mapping(value, field, errors)
    if receipt is None:
        return None
    _nonempty_text(receipt.get("summary"), f"{field}.summary", errors)
    for key in RECEIPT_TEXT_FIELDS:
        _nonempty_text(receipt.get(key), f"{field}.{key}", errors)
    event_time = _utc_timestamp(receipt.get("event_time"), f"{field}.event_time", errors)
    recorded_at = _utc_timestamp(receipt.get("recorded_at"), f"{field}.recorded_at", errors)
    if event_time is not None and recorded_at is not None and recorded_at < event_time:
        errors.append(f"{field}.recorded_at MUST not precede event_time")
    digest = receipt.get("provenance_digest")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        errors.append(f"{field}.provenance_digest MUST be a lowercase SHA-256 digest")
    if not isinstance(receipt.get("synthetic"), bool):
        errors.append(f"{field}.synthetic MUST be a boolean")
    return receipt


def _validate_measurements(
    value: object,
    scenario_id: str,
    errors: list[str],
    *,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
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
        observed_at = _utc_timestamp(
            measurement.get("observed_at"),
            f"{field}[{index}].observed_at",
            errors,
        )
        if (
            observed_at is not None
            and window_start is not None
            and window_end is not None
            and not window_start <= observed_at <= window_end
        ):
            errors.append(f"{field}[{index}].observed_at MUST be inside the scenario time_window")


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

    start: datetime | None = None
    end: datetime | None = None
    window = _mapping(scenario.get("time_window"), f"{field}.time_window", errors)
    if window is not None:
        start = _utc_timestamp(window.get("start"), f"{field}.time_window.start", errors)
        end = _utc_timestamp(window.get("end"), f"{field}.time_window.end", errors)
        if start is not None and end is not None and end < start:
            errors.append(f"{field}.time_window.end MUST not precede start")

    evidence_receipts: list[Mapping[str, Any]] = []
    for evidence_name in ("injection_evidence", "detection_evidence"):
        receipt = _validate_evidence_receipt(
            scenario.get(evidence_name),
            f"{field}.{evidence_name}",
            errors,
        )
        if receipt is not None:
            evidence_receipts.append(receipt)

    root_cause = _mapping(scenario.get("root_cause"), f"{field}.root_cause", errors)
    if root_cause is not None:
        _nonempty_text(root_cause.get("summary"), f"{field}.root_cause.summary", errors)
        if root_cause.get("confidence") not in ("high", "medium", "low", "unknown"):
            errors.append(f"{field}.root_cause.confidence MUST be high, medium, low, or unknown")
        if not isinstance(root_cause.get("alternatives"), list):
            errors.append(f"{field}.root_cause.alternatives MUST be an array")

    _validate_measurements(
        scenario.get("measurements"),
        scenario_id,
        errors,
        window_start=start,
        window_end=end,
    )

    recovery = _validate_evidence_receipt(
        scenario.get("recovery_evidence"),
        f"{field}.recovery_evidence",
        errors,
    )
    if recovery is not None:
        evidence_receipts.append(recovery)
        recovery_status = recovery.get("status")
        if recovery_status not in RECOVERY_STATUSES:
            errors.append(
                f"{field}.recovery_evidence.status MUST be one of: {', '.join(RECOVERY_STATUSES)}"
            )
        expected_recovery = "not-applicable" if scenario_id in ("S13", "S14") else "verified"
        if status == "passed" and recovery_status != expected_recovery:
            errors.append(
                f"{field} passed status requires recovery_evidence.status={expected_recovery}"
            )

    if status == "passed" and any(
        receipt.get("synthetic") is True for receipt in evidence_receipts
    ):
        errors.append(f"{field} MUST NOT be passed using synthetic decision evidence")

    safety = _mapping(scenario.get("safety"), f"{field}.safety", errors)
    if safety is not None:
        for key in ("approval", "blast_radius", "stop_condition", "rollback"):
            _nonempty_text(safety.get(key), f"{field}.safety.{key}", errors)

    cleanup = _mapping(scenario.get("cleanup"), f"{field}.cleanup", errors)
    if cleanup is not None:
        cleanup_status = cleanup.get("status")
        if cleanup_status not in ("verified", "incomplete", "not-applicable"):
            errors.append(f"{field}.cleanup.status MUST be verified, incomplete, or not-applicable")
        if (
            status == "passed"
            and scenario_id not in ("S13", "S14")
            and cleanup_status != "verified"
        ):
            errors.append(f"{field} passed fault status requires cleanup.status=verified")
        residuals = cleanup.get("residuals")
        if not isinstance(residuals, list):
            errors.append(f"{field}.cleanup.residuals MUST be an array")
        elif status == "passed" and residuals:
            errors.append(f"{field}.cleanup.residuals MUST be empty for passed status")

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


def build_sanitized_summary(
    payload: Mapping[str, Any],
    *,
    source_ledger_sha256: str,
) -> dict[str, Any]:
    """Project a validated live ledger into a customer-agnostic tracked summary."""
    if _SHA256.fullmatch(source_ledger_sha256) is None:
        raise ValueError("source_ledger_sha256 MUST be a lowercase SHA-256 digest")
    scenarios = payload["scenarios"]
    if not isinstance(scenarios, Mapping):
        raise ValueError("scenarios MUST be an object")

    entries: list[dict[str, Any]] = []
    for scenario_id in SCENARIO_IDS:
        scenario = scenarios[scenario_id]
        if not isinstance(scenario, Mapping):
            raise ValueError(f"scenarios.{scenario_id} MUST be an object")
        recovery = scenario["recovery_evidence"]
        cleanup = scenario["cleanup"]
        measurements = scenario["measurements"]
        unsupported_claims = scenario["unsupported_claims"]
        if not isinstance(recovery, Mapping) or not isinstance(cleanup, Mapping):
            raise ValueError(f"scenarios.{scenario_id} evidence MUST be objects")
        if not isinstance(measurements, Sequence) or isinstance(measurements, (str, bytes)):
            raise ValueError(f"scenarios.{scenario_id}.measurements MUST be an array")
        if not isinstance(unsupported_claims, Sequence) or isinstance(
            unsupported_claims, (str, bytes)
        ):
            raise ValueError(f"scenarios.{scenario_id}.unsupported_claims MUST be an array")

        receipts = (
            scenario["injection_evidence"],
            scenario["detection_evidence"],
            recovery,
        )
        provenance_digests = sorted(
            {
                str(receipt["provenance_digest"])
                for receipt in receipts
                if isinstance(receipt, Mapping)
            }
        )
        synthetic = any(
            receipt.get("synthetic") is True for receipt in receipts if isinstance(receipt, Mapping)
        )
        safe_measurements = [
            {
                "name": measurement["name"],
                "unit": measurement["unit"],
                "value": measurement["value"],
            }
            for measurement in measurements
            if isinstance(measurement, Mapping)
        ]
        residuals = cleanup.get("residuals")
        entries.append(
            {
                "cleanup_status": cleanup["status"],
                "measurements": safe_measurements,
                "provenance_digests": provenance_digests,
                "recovery_status": recovery["status"],
                "residual_count": len(residuals) if isinstance(residuals, list) else 0,
                "scenario_id": scenario_id,
                "synthetic": synthetic,
                "unsupported_claim_count": len(unsupported_claims),
                "verdict": scenario["status"],
            }
        )

    return {
        "entries": entries,
        "evidence_level": "live_execution",
        "generated_at": payload["generated_at"],
        "scenario_set": "sre-agent-s1-s14",
        "schema_version": 1,
        "source_ledger_sha256": source_ledger_sha256,
        "summary": payload["summary"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Write a deterministic customer-agnostic tracked summary after validation.",
    )
    args = parser.parse_args(argv)
    try:
        source_bytes = args.ledger.read_bytes()
        payload = json.loads(source_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"sre-evidence: ERROR: cannot read ledger: {exc}", file=sys.stderr)
        return 1
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"sre-evidence: ERROR: {error}", file=sys.stderr)
        return 1
    if args.summary_output is not None:
        summary = build_sanitized_summary(
            payload,
            source_ledger_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print("sre-evidence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
