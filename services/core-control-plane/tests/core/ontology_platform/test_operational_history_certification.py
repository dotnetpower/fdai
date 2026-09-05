"""OI-16 pinned-revision operational history certification tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryProtectedBinding,
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
IMAGE = "sha256:" + "d" * 64
ATTESTATION = "sha256:" + "e" * 64
SOURCE = "376dc306765e6a182542f2818e14c9b73d0d1a38"
RUNTIME_SOURCE = SOURCE


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


def _binding() -> OperationalHistoryProtectedBinding:
    return OperationalHistoryProtectedBinding(
        source_revision=SOURCE,
        required_ci_run_id=101,
        runtime_image_revision=RUNTIME_SOURCE,
        runtime_image_digest=IMAGE,
        runtime_attestation_digest=ATTESTATION,
        deployment_revision="69bbdf6c10f2c654c1177cfa912f143f57faf263",
        deployment_apply_run_id=303,
        deployment_receipt_digest=DEPLOYMENT,
        campaign_run_id=202,
        campaign_request_id="certify-history-" + "f" * 48,
    )


def _build(*, deployment: str | None = None, protected=False, unavailable=None):
    return build_operational_history_certification(
        _results(unavailable=unavailable),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW,
        window_end=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1, seconds=1),
        deployment_receipt_digest=deployment,
        protected_binding=_binding() if protected else None,
    )


def test_local_deterministic_receipt_cannot_claim_operational_validation() -> None:
    receipt = _build()

    assert receipt.deterministic_complete is True
    assert receipt.operationally_validated is False
    assert receipt.deployment_receipt_digest is None
    assert receipt.execution_authority is False


def test_complete_protected_binding_is_required_for_operational_validation() -> None:
    receipt = _build(deployment=DEPLOYMENT, protected=True)
    replay = _build(deployment=DEPLOYMENT, protected=True)

    assert receipt.operationally_validated is True
    assert receipt.digest == replay.digest
    assert certification_record(receipt)["source_revision"] == receipt.source_revision


def test_any_unavailable_failure_scenario_prevents_complete_claim() -> None:
    receipt = _build(
        deployment=DEPLOYMENT,
        protected=True,
        unavailable=OperationalHistoryScenario.ARCHIVE_OUTAGE,
    )

    assert receipt.deterministic_complete is False
    assert receipt.operationally_validated is False


def test_deployment_receipt_without_protected_binding_cannot_validate() -> None:
    assert _build(deployment=DEPLOYMENT).operationally_validated is False


def test_protected_binding_must_match_source_and_deployment_receipt() -> None:
    with pytest.raises(ValueError, match="source revision"):
        build_operational_history_certification(
            _results(),
            source_revision=SOURCE,
            ontology_release_digest=RELEASE,
            window_start=NOW,
            window_end=NOW + timedelta(hours=1),
            recorded_at=NOW + timedelta(hours=1, seconds=1),
            deployment_receipt_digest=DEPLOYMENT,
            protected_binding=replace(
                _binding(),
                source_revision="a" * 40,
                runtime_image_revision="a" * 40,
            ),
        )


def test_protected_binding_requires_runtime_image_from_source_revision() -> None:
    with pytest.raises(ValueError, match="runtime image revision does not match"):
        replace(
            _binding(),
            runtime_image_revision="780d8782ad48c2911c626ce961d0788969ec2a1d",
        )


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
