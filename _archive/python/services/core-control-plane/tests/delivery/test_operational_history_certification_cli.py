"""OI-16 certification manifest and private artifact tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryProtectedBinding,
    OperationalHistoryScenario,
)
from fdai.delivery.operational_history_certification_cli import (
    _write_private,
    build_certification_from_manifest,
    run,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64
DEPLOYMENT = "sha256:" + "c" * 64
IMAGE = "sha256:" + "d" * 64
ATTESTATION = "sha256:" + "e" * 64
SOURCE = "376dc306765e6a182542f2818e14c9b73d0d1a38"
CAMPAIGN_ID = "certify-history-" + "f" * 48


def _manifest(*, omit: OperationalHistoryScenario | None = None):
    return {
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN_ID,
        "phase": "merged",
        "source_revision_digest": "sha256:" + hashlib.sha256(SOURCE.encode()).hexdigest(),
        "ontology_release_digest": RELEASE,
        "window_start": NOW.isoformat(),
        "window_end": (NOW + timedelta(hours=1)).isoformat(),
        "recorded_at": (NOW + timedelta(hours=1, seconds=1)).isoformat(),
        "deterministic_complete": omit is None,
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


def _binding() -> OperationalHistoryProtectedBinding:
    return OperationalHistoryProtectedBinding(
        source_revision=SOURCE,
        required_ci_run_id=101,
        runtime_image_revision=SOURCE,
        runtime_image_digest=IMAGE,
        runtime_attestation_digest=ATTESTATION,
        deployment_revision="69bbdf6c10f2c654c1177cfa912f143f57faf263",
        deployment_apply_run_id=303,
        deployment_receipt_digest=DEPLOYMENT,
        campaign_run_id=202,
        campaign_request_id=CAMPAIGN_ID,
    )


def test_complete_local_manifest_stays_not_operationally_validated() -> None:
    receipt = build_certification_from_manifest(
        _manifest(),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
    )

    assert receipt.deterministic_complete is True
    assert receipt.operationally_validated is False


def test_missing_failure_scenario_is_explicitly_unavailable() -> None:
    receipt = build_certification_from_manifest(
        _manifest(omit=OperationalHistoryScenario.ARCHIVE_OUTAGE),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
    )

    assert receipt.deterministic_complete is False
    assert receipt.operationally_validated is False


def test_complete_protected_manifest_is_operationally_validated() -> None:
    receipt = build_certification_from_manifest(
        _manifest(),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        deployment_receipt_digest=DEPLOYMENT,
        protected_binding=_binding(),
    )

    assert receipt.operationally_validated is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("source_revision_digest", "sha256:" + "0" * 64, "source revision"),
        ("ontology_release_digest", "sha256:" + "0" * 64, "ontology release"),
        ("campaign_id", "certify-history-" + "0" * 48, "campaign request"),
        ("phase", "single_pass", "merged restart-phase"),
    ),
)
def test_protected_manifest_rejects_mismatched_binding(
    field: str, value: str, message: str
) -> None:
    manifest = _manifest()
    manifest[field] = value

    with pytest.raises(ValueError, match=message):
        build_certification_from_manifest(
            manifest,
            source_revision=SOURCE,
            ontology_release_digest=RELEASE,
            deployment_receipt_digest=DEPLOYMENT,
            protected_binding=_binding(),
        )


def test_incomplete_campaign_is_not_persisted_or_written(tmp_path, monkeypatch) -> None:
    evidence = tmp_path / "evidence.json"
    output = tmp_path / "receipt.json"
    evidence.write_text(
        json.dumps(_manifest(omit=OperationalHistoryScenario.ARCHIVE_OUTAGE)),
        encoding="utf-8",
    )

    def unexpected_store(**_kwargs):
        raise AssertionError("incomplete campaigns must not initialize persistence")

    monkeypatch.setattr(
        "fdai.delivery.operational_history_certification_cli.PostgresOperationalHistoryStore",
        unexpected_store,
    )
    summary = asyncio.run(
        run(
            evidence_path=evidence,
            output_path=output,
            source_revision=SOURCE,
            ontology_release_digest=RELEASE,
            dsn="postgresql://unused",
            deployment_receipt_digest=DEPLOYMENT,
            protected_binding=_binding(),
        )
    )

    assert summary["operationally_validated"] is False
    assert summary["persisted"] is False
    assert summary["output"] is None
    assert not output.exists()


def test_certification_artifact_is_private_and_atomic(tmp_path) -> None:
    output = tmp_path / "receipt.json"

    _write_private(output, {"schema_version": "1.0.0"})

    assert os.stat(output).st_mode & 0o777 == 0o600
