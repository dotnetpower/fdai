from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.detection.configuration_drift import (
    ConfigurationDriftPerformance,
    ConfigurationDriftReport,
    DriftFinding,
    DriftType,
    DriftVerdict,
    KnowledgeGroundingStatus,
)
from fdai.core.detection.configuration_drift_codec import report_from_dict, report_to_dict


def _report() -> ConfigurationDriftReport:
    return ConfigurationDriftReport(
        baseline_version="v1",
        baseline_sha256="a" * 64,
        scope="example-scope",
        observed_at=datetime(2026, 8, 4, tzinfo=UTC),
        verdict=DriftVerdict.FAILED,
        findings=(
            DriftFinding(
                target="service-a",
                field="sku",
                baseline_value={"name": "Standard", "capacity": 1},
                actual_value={"name": "Premium", "capacity": 2},
                verdict=DriftVerdict.FAILED,
                drift_type=DriftType.CHANGED,
                source="authoritative inventory",
            ),
        ),
        knowledge_status=KnowledgeGroundingStatus.CITED,
        knowledge_citations=("knowledge:baseline:a#0",),
        performance=ConfigurationDriftPerformance(
            baseline_load_ms=1.0,
            observation_ms=2.0,
            comparison_ms=3.0,
            knowledge_ms=4.0,
            total_ms=10.0,
            resource_count=1,
            finding_count=1,
        ),
    )


def test_report_codec_round_trips_full_replay_evidence() -> None:
    report = _report()

    restored = report_from_dict(report_to_dict(report))

    assert restored == report


def test_report_codec_rejects_unknown_fields() -> None:
    raw = report_to_dict(_report())
    raw["unexpected"] = True

    with pytest.raises(ValueError, match="report has unknown fields"):
        report_from_dict(raw)


def test_performance_rejects_impossible_stage_total() -> None:
    with pytest.raises(ValueError, match="stage latencies MUST NOT exceed total"):
        ConfigurationDriftPerformance(
            baseline_load_ms=4.0,
            observation_ms=4.0,
            comparison_ms=4.0,
            knowledge_ms=4.0,
            total_ms=10.0,
            resource_count=1,
            finding_count=1,
        )
