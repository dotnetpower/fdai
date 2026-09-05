"""OI-16 pinned-revision operational history certification tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioResult,
    OperationalHistoryScenarioStatus,
    build_operational_history_certification,
    build_operational_history_recovery_receipt,
    certification_record,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64
DEPLOYMENT = "sha256:" + "c" * 64


def _results(
    *,
    unavailable: OperationalHistoryScenario | None = None,
) -> tuple[OperationalHistoryScenarioResult, ...]:
    return tuple(
        OperationalHistoryScenarioResult(
            scenario=scenario,
            status=(
                OperationalHistoryScenarioStatus.UNAVAILABLE
                if scenario is unavailable
                else OperationalHistoryScenarioStatus.PASSED
            ),
            evidence_digests=(EVIDENCE,),
            reason_codes=(
                ("protected_deployment_receipt_unavailable",) if scenario is unavailable else ()
            ),
        )
        for scenario in OperationalHistoryScenario
    )


def _build(*, deployment: str | None = None, unavailable=None):
    return build_operational_history_certification(
        _results(unavailable=unavailable),
        source_revision="376dc306765e6a182542f2818e14c9b73d0d1a38",
        ontology_release_digest=RELEASE,
        window_start=NOW,
        window_end=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1, seconds=1),
        deployment_receipt_digest=deployment,
    )


def test_local_deterministic_receipt_cannot_claim_operational_validation() -> None:
    receipt = _build()

    assert receipt.deterministic_complete is True
    assert receipt.operationally_validated is False
    assert receipt.deployment_receipt_digest is None
    assert receipt.execution_authority is False


def test_pinned_deployment_receipt_is_required_for_operational_validation() -> None:
    receipt = _build(deployment=DEPLOYMENT)
    replay = _build(deployment=DEPLOYMENT)

    assert receipt.operationally_validated is True
    assert receipt.digest == replay.digest
    assert certification_record(receipt)["source_revision"] == receipt.source_revision


def test_any_unavailable_failure_scenario_prevents_complete_claim() -> None:
    receipt = _build(
        deployment=DEPLOYMENT,
        unavailable=OperationalHistoryScenario.ARCHIVE_OUTAGE,
    )

    assert receipt.deterministic_complete is False
    assert receipt.operationally_validated is False


def test_missing_scenario_or_digest_tampering_is_rejected() -> None:
    receipt = _build()
    with pytest.raises(ValueError, match="every ordered OI-16 scenario"):
        replace(receipt, scenario_results=receipt.scenario_results[:-1])
    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, digest=DEPLOYMENT)


@pytest.mark.parametrize(
    "scenario",
    (
        OperationalHistoryScenario.DUPLICATE_DELIVERY,
        OperationalHistoryScenario.LATE_OBSERVATION,
        OperationalHistoryScenario.DELETE_RECREATE,
        OperationalHistoryScenario.PROVIDER_FAILURE,
        OperationalHistoryScenario.DATABASE_RESTART,
        OperationalHistoryScenario.ARCHIVE_OUTAGE,
    ),
)
def test_every_false_complete_failure_case_is_explicit(
    scenario: OperationalHistoryScenario,
) -> None:
    receipt = _build(unavailable=scenario)
    result = next(item for item in receipt.scenario_results if item.scenario is scenario)

    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert receipt.operationally_validated is False


def test_database_recovery_requires_equal_watermarks_and_archive_index() -> None:
    recovered = build_operational_history_recovery_receipt(
        source_revision="revision-1",
        before_journal_watermark=10,
        after_journal_watermark=10,
        before_projection_watermark=9,
        after_projection_watermark=9,
        before_archive_index_digest=EVIDENCE,
        after_archive_index_digest=EVIDENCE,
        recovered_at=NOW,
    )
    incomplete = build_operational_history_recovery_receipt(
        source_revision="revision-1",
        before_journal_watermark=10,
        after_journal_watermark=9,
        before_projection_watermark=9,
        after_projection_watermark=9,
        before_archive_index_digest=EVIDENCE,
        after_archive_index_digest=EVIDENCE,
        recovered_at=NOW,
    )

    assert recovered.complete is True
    assert incomplete.complete is False
    assert recovered.digest != incomplete.digest
