"""Sanitized, fingerprint-bound summaries for chaos catalog validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from fdai.core.chaos.scenario_catalog import CatalogEntry, catalog_fingerprint

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CatalogEvidenceLevel(StrEnum):
    DISPATCHABILITY = "dispatchability"
    LIVE_SHADOW = "live_shadow"
    LIVE_ENFORCE = "live_enforce"


class CatalogEvidenceOutcome(StrEnum):
    DISPATCHABLE = "dispatchable"
    SKIPPED_NON_EXECUTABLE = "skipped_non_executable"
    BUILD_ERROR = "build_error"
    VALIDATED = "validated"
    NOT_DETECTED = "not_detected"
    DRIVER_ERROR = "driver_error"
    ROLLBACK_FAILED = "rollback_failed"


@dataclass(frozen=True, slots=True)
class CatalogEvidenceEntry:
    scenario_id: str
    scenario_version: int
    outcome: CatalogEvidenceOutcome
    detected: bool | None = None
    rollback_succeeded: bool | None = None
    detection_latency_ms: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "outcome": self.outcome.value,
            "detected": self.detected,
            "rollback_succeeded": self.rollback_succeeded,
            "detection_latency_ms": self.detection_latency_ms,
        }


@dataclass(frozen=True, slots=True)
class CatalogValidationSummary:
    generated_at: datetime
    evidence_level: CatalogEvidenceLevel
    catalog_fingerprint: str
    runner_version: str
    entries: tuple[CatalogEvidenceEntry, ...]
    full_bundle_sha256: str | None = None
    full_bundle_retention_days: int = 90
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at MUST be timezone-aware")
        if not _SHA256.fullmatch(self.catalog_fingerprint):
            raise ValueError("catalog_fingerprint MUST be a SHA-256 hex digest")
        if self.full_bundle_sha256 is not None and not _SHA256.fullmatch(self.full_bundle_sha256):
            raise ValueError("full_bundle_sha256 MUST be a SHA-256 hex digest")
        if self.full_bundle_retention_days < 1:
            raise ValueError("full_bundle_retention_days MUST be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "evidence_level": self.evidence_level.value,
            "catalog_fingerprint": self.catalog_fingerprint,
            "runner_version": self.runner_version,
            "catalog_entry_count": len(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
            "full_bundle": {
                "storage": "ci_or_release_artifact",
                "sha256": self.full_bundle_sha256,
                "retention_days": self.full_bundle_retention_days,
            },
        }


def build_catalog_validation_summary(
    *,
    entries: Sequence[CatalogEntry],
    reports: Mapping[str, Mapping[str, Any]],
    evidence_level: CatalogEvidenceLevel,
    runner_version: str,
    generated_at: datetime | None = None,
    full_bundle_sha256: str | None = None,
) -> CatalogValidationSummary:
    """Build an allowlist-only summary from potentially sensitive reports."""
    summarized = tuple(
        _summarize_entry(entry, reports.get(entry.id))
        for entry in sorted(entries, key=lambda item: item.id)
    )
    return CatalogValidationSummary(
        generated_at=generated_at or datetime.now(tz=UTC),
        evidence_level=evidence_level,
        catalog_fingerprint=catalog_fingerprint(list(entries)),
        runner_version=runner_version,
        entries=summarized,
        full_bundle_sha256=full_bundle_sha256,
    )


def write_catalog_validation_summary(summary: CatalogValidationSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n")


def assert_catalog_summary_current(
    summary: Mapping[str, Any],
    entries: Sequence[CatalogEntry],
) -> None:
    expected_fingerprint = catalog_fingerprint(list(entries))
    if summary.get("catalog_fingerprint") != expected_fingerprint:
        raise ValueError("catalog validation summary is stale")
    expected = {(entry.id, int(entry.spec["version"])) for entry in entries}
    raw_entries = summary.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("catalog validation summary entries MUST be a list")
    actual = {
        (str(item.get("scenario_id")), int(item.get("scenario_version", 0)))
        for item in raw_entries
        if isinstance(item, dict)
    }
    if actual != expected:
        raise ValueError("catalog validation summary scenario set is stale")


def _summarize_entry(
    entry: CatalogEntry,
    report: Mapping[str, Any] | None,
) -> CatalogEvidenceEntry:
    if report is None:
        return CatalogEvidenceEntry(
            scenario_id=entry.id,
            scenario_version=int(entry.spec["version"]),
            outcome=CatalogEvidenceOutcome.SKIPPED_NON_EXECUTABLE,
        )
    raw_outcome = str(report.get("outcome") or "build_error")
    try:
        outcome = CatalogEvidenceOutcome(raw_outcome)
    except ValueError:
        outcome = CatalogEvidenceOutcome.DRIVER_ERROR
    latency = report.get("detection_latency_ms")
    return CatalogEvidenceEntry(
        scenario_id=entry.id,
        scenario_version=int(entry.spec["version"]),
        outcome=outcome,
        detected=report.get("detected") if isinstance(report.get("detected"), bool) else None,
        rollback_succeeded=(
            report.get("reverted") if isinstance(report.get("reverted"), bool) else None
        ),
        detection_latency_ms=(
            int(latency) if isinstance(latency, int | float) and latency >= 0 else None
        ),
    )


__all__ = [
    "CatalogEvidenceEntry",
    "CatalogEvidenceLevel",
    "CatalogEvidenceOutcome",
    "CatalogValidationSummary",
    "assert_catalog_summary_current",
    "build_catalog_validation_summary",
    "write_catalog_validation_summary",
]
