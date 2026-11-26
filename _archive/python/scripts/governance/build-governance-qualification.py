#!/usr/bin/env python3
"""Build the F06.2 governance qualification record from one private evidence input.

The input is one JSON object with ``binding``, ``required_source_ids``, ``max_age_seconds``,
``observations``, and an optional ``cohort`` with its frozen ``digest``. The output is the
review-only record: it lists every hold and blocker by name and grants no authority. Exit code
0 means the record is ready for review, 2 means it is blocked, 1 means the input is invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fdai.core.governance_qualification import (
    CohortCase,
    CohortMeasurement,
    GroundTruth,
    QualificationBinding,
    Rate,
    Readiness,
    SourceObservation,
    SourceState,
    Verdict,
    build_qualification_record,
    freeze_cohort,
    measure_cohort,
    reconcile_sources,
)


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("time MUST be an ISO 8601 string")
    return datetime.fromisoformat(value)


def _rate(rate: Rate | None) -> object:
    if rate is None:
        return None
    return {
        "numerator": rate.numerator,
        "denominator": rate.denominator,
        "value": rate.value,
        "lower": rate.lower,
        "upper": rate.upper,
    }


def _measurement(measurement: CohortMeasurement) -> dict[str, object]:
    return {
        "cohort_digest": measurement.cohort_digest,
        "total": measurement.total,
        "independent_groups": measurement.independent_groups,
        "true_positive": measurement.true_positive,
        "false_positive": measurement.false_positive,
        "false_negative": measurement.false_negative,
        "true_negative": measurement.true_negative,
        "held_violation": measurement.held_violation,
        "held_compliant": measurement.held_compliant,
        "coverage": _rate(measurement.coverage),
        "false_positive_rate": _rate(measurement.false_positive_rate),
        "false_negative_rate": _rate(measurement.false_negative_rate),
        "false_negative_rate_worst_case": _rate(measurement.false_negative_rate_worst_case),
        "digest": measurement.digest,
    }


def build(document: dict[str, object]) -> tuple[dict[str, object], Readiness]:
    binding_value = document["binding"]
    if not isinstance(binding_value, dict):
        raise ValueError("binding MUST be an object")
    binding = QualificationBinding(
        installation_id=str(binding_value["installation_id"]),
        management_scope_id=str(binding_value["management_scope_id"]),
        environment_class=str(binding_value["environment_class"]),
        rule_generation_digest=str(binding_value["rule_generation_digest"]),
        ontology_release_digest=str(binding_value["ontology_release_digest"]),
        provider_revisions={
            str(k): str(v) for k, v in dict(binding_value["provider_revisions"]).items()
        },
        evidence_cutoff=_time(binding_value["evidence_cutoff"]),
    )
    observations = [
        SourceObservation(
            source_id=str(item["source_id"]),
            scope_id=str(item["scope_id"]),
            identity_ref=str(item["identity_ref"]),
            state=SourceState(str(item["state"])),
            observed_at=_time(item["observed_at"]),
            evidence_digest=str(item["evidence_digest"]),
        )
        for item in list(document["observations"])  # type: ignore[call-overload]
    ]
    sources = reconcile_sources(
        observations,
        required_source_ids=[str(item) for item in list(document["required_source_ids"])],  # type: ignore[call-overload]
        evidence_cutoff=binding.evidence_cutoff,
        max_age=timedelta(seconds=int(document["max_age_seconds"])),  # type: ignore[call-overload]
    )
    measurement: CohortMeasurement | None = None
    cohort_value = document.get("cohort")
    if cohort_value is not None:
        if not isinstance(cohort_value, dict):
            raise ValueError("cohort MUST be an object")
        cohort = freeze_cohort(
            CohortCase(
                case_id=str(case["case_id"]),
                group_id=str(case["group_id"]),
                truth=GroundTruth(str(case["truth"])),
                verdict=Verdict(str(case["verdict"])),
            )
            for case in list(cohort_value["cases"])
        )
        measurement = measure_cohort(cohort, expected_digest=str(cohort_value["digest"]))
    record = build_qualification_record(binding, sources, measurement)
    output: dict[str, object] = {
        "schema_version": "fdai.governance-qualification-record.v1",
        "readiness": record.readiness.value,
        "blocking_reasons": list(record.blocking_reasons),
        "authority": record.authority,
        "record_digest": record.record_digest,
        "sources_digest": record.sources_digest,
        "holds": [[hold.source_id, hold.reason.value] for hold in sources.holds],
        "measurement": _measurement(measurement) if measurement is not None else None,
    }
    return output, record.readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="private evidence input JSON")
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("input MUST be a JSON object")
        output, readiness = build(document)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            f"build-governance-qualification: invalid input: {type(exc).__name__}", file=sys.stderr
        )
        return 1
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if readiness is Readiness.READY_FOR_REVIEW else 2


if __name__ == "__main__":
    raise SystemExit(main())
