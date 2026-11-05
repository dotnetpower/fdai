from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.chaos.catalog_evidence import (
    CatalogEvidenceLevel,
    CatalogEvidenceOutcome,
    CatalogValidationSummary,
    assert_catalog_summary_current,
    build_catalog_validation_summary,
    write_catalog_validation_summary,
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


def test_catalog_validation_summary_validates_fields_and_writes_json(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    digest = "a" * 64
    with pytest.raises(ValueError, match="timezone-aware"):
        CatalogValidationSummary(
            generated_at=datetime(2026, 7, 17),
            evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
            catalog_fingerprint=digest,
            runner_version="runner/1",
            entries=(),
        )
    with pytest.raises(ValueError, match="runner_version"):
        CatalogValidationSummary(
            generated_at=now,
            evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
            catalog_fingerprint=digest,
            runner_version="   ",
            entries=(),
        )
    with pytest.raises(ValueError, match="catalog_fingerprint"):
        CatalogValidationSummary(
            generated_at=now,
            evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
            catalog_fingerprint="not-a-digest",
            runner_version="runner/1",
            entries=(),
        )
    with pytest.raises(ValueError, match="full_bundle_sha256"):
        CatalogValidationSummary(
            generated_at=now,
            evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
            catalog_fingerprint=digest,
            runner_version="runner/1",
            entries=(),
            full_bundle_sha256="bad-digest",
        )
    with pytest.raises(ValueError, match="full_bundle_retention_days"):
        CatalogValidationSummary(
            generated_at=now,
            evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
            catalog_fingerprint=digest,
            runner_version="runner/1",
            entries=(),
            full_bundle_retention_days=0,
        )

    entry = _entry("chaos.test.one")
    summary = build_catalog_validation_summary(
        entries=[entry],
        reports={entry.id: {"outcome": "unrecognized_outcome"}},
        evidence_level=CatalogEvidenceLevel.LIVE_SHADOW,
        runner_version="runner/1",
        generated_at=now,
        full_bundle_sha256="b" * 64,
    )
    assert summary.entries[0].outcome is CatalogEvidenceOutcome.DRIVER_ERROR
    out_path = tmp_path / "nested" / "summary.json"
    write_catalog_validation_summary(summary, out_path)
    assert out_path.is_file()

    raw = summary.to_dict()
    with pytest.raises(ValueError, match="MUST be a list"):
        assert_catalog_summary_current({**raw, "entries": "invalid"}, [entry])
    with pytest.raises(ValueError, match="scenario set is stale"):
        assert_catalog_summary_current({**raw, "entries": ["not-a-dict"]}, [entry])
