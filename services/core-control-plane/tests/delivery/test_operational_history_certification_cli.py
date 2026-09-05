"""OI-16 certification manifest and private artifact tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
)
from fdai.delivery.operational_history_certification_cli import (
    _write_private,
    build_certification_from_manifest,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64


def _manifest(*, omit: OperationalHistoryScenario | None = None):
    return {
        "schema_version": "1.0.0",
        "window_start": NOW.isoformat(),
        "window_end": (NOW + timedelta(hours=1)).isoformat(),
        "recorded_at": (NOW + timedelta(hours=1, seconds=1)).isoformat(),
        "scenarios": {
            scenario.value: {
                "status": "passed",
                "evidence_digests": [EVIDENCE],
                "reason_codes": [],
            }
            for scenario in OperationalHistoryScenario
            if scenario is not omit
        },
    }


def test_complete_local_manifest_stays_not_operationally_validated() -> None:
    receipt = build_certification_from_manifest(
        _manifest(),
        source_revision="376dc306765e6a182542f2818e14c9b73d0d1a38",
        ontology_release_digest=RELEASE,
    )

    assert receipt.deterministic_complete is True
    assert receipt.operationally_validated is False


def test_missing_failure_scenario_is_explicitly_unavailable() -> None:
    receipt = build_certification_from_manifest(
        _manifest(omit=OperationalHistoryScenario.ARCHIVE_OUTAGE),
        source_revision="376dc306765e6a182542f2818e14c9b73d0d1a38",
        ontology_release_digest=RELEASE,
    )

    assert receipt.deterministic_complete is False
    assert receipt.operationally_validated is False


def test_certification_artifact_is_private_and_atomic(tmp_path) -> None:
    output = tmp_path / "receipt.json"

    _write_private(output, {"schema_version": "1.0.0"})

    assert os.stat(output).st_mode & 0o777 == 0o600
