from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.chaos.catalog_evidence import (
    CatalogEvidenceLevel,
    assert_catalog_summary_current,
    build_catalog_validation_summary,
)
from fdai.core.chaos.scenario_catalog import CatalogEntry


def _entry(scenario_id: str, version: int = 1) -> CatalogEntry:
    return CatalogEntry(
        id=scenario_id,
        source_path=Path("scenario.yaml"),
        spec={"id": scenario_id, "version": version},
    )


def test_summary_whitelists_fields_and_omits_sensitive_report_values() -> None:
    entry = _entry("chaos.test.one")
    summary = build_catalog_validation_summary(
        entries=[entry],
        reports={
            entry.id: {
                "outcome": "validated",
                "detected": True,
                "reverted": True,
                "detection_latency_ms": 250,
                "approval_ref": "private-approval",
                "targets": ["private-resource"],
                "error": "private-endpoint",
            }
        },
        evidence_level=CatalogEvidenceLevel.LIVE_ENFORCE,
        runner_version="run-catalog-scenario/1",
        generated_at=datetime(2026, 7, 17, tzinfo=UTC),
    )

    payload = summary.to_dict()
    rendered = str(payload)
    assert payload["catalog_entry_count"] == 1
    assert payload["entries"][0]["outcome"] == "validated"
    assert "private-approval" not in rendered
    assert "private-resource" not in rendered
    assert "private-endpoint" not in rendered


def test_summary_freshness_rejects_catalog_or_version_change() -> None:
    entry = _entry("chaos.test.one")
    summary = build_catalog_validation_summary(
        entries=[entry],
        reports={},
        evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
        runner_version="run-catalog-scenario/1",
    ).to_dict()

    assert_catalog_summary_current(summary, [entry])
    with pytest.raises(ValueError, match="stale"):
        assert_catalog_summary_current(summary, [_entry(entry.id, version=2)])
