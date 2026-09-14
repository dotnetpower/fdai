"""Focused result-state semantics for live operational activity."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery.observation_campaign import (
    ObservationSourceSpec,
    _activity,
)
from fdai.delivery.operational_activity import (
    current_state_activity,
    ontology_projection_activity,
)
from fdai_service_contracts import (
    ObservationDomain,
    OperationalActivityResultState,
    OperationalActivityStatus,
    OperationalFreshness,
)


def test_degraded_partial_results_remain_measured() -> None:
    current = current_state_activity(
        correlation_id="correlation-1",
        status=OperationalActivityStatus.DEGRADED,
        freshness=OperationalFreshness.UNKNOWN,
        evidence_count=2,
        reason_codes=("cross_source_conflict",),
    )
    ontology = ontology_projection_activity(
        generation="generation-1",
        status=OperationalActivityStatus.DEGRADED,
        freshness=OperationalFreshness.UNAVAILABLE,
        evidence_count=3,
        reason_codes=("partial_projection",),
    )

    assert current.result_state is OperationalActivityResultState.MEASURED
    assert current.result_count == 2
    assert ontology.result_state is OperationalActivityResultState.MEASURED
    assert ontology.result_count == 3


def test_failed_ontology_projection_does_not_claim_pre_failure_count() -> None:
    activity = ontology_projection_activity(
        generation="generation-1",
        status=OperationalActivityStatus.FAILED,
        freshness=OperationalFreshness.UNAVAILABLE,
        evidence_count=3,
        reason_codes=("projection_failed",),
    )

    assert activity.result_state is OperationalActivityResultState.UNAVAILABLE
    assert activity.evidence_count == 0
    assert activity.result_count is None


def test_superseded_observation_does_not_fabricate_measured_zero() -> None:
    spec = ObservationSourceSpec(
        source_id="activity-log",
        domain=ObservationDomain.ACTIVITY_LOG,
        owner_agent="Huginn",
        interval_seconds=60,
        lookback_seconds=300,
        timeout_seconds=1,
        max_targets=16,
        max_results=100,
        max_output_bytes=64_000,
        required=True,
    )

    activity = _activity(
        spec=spec,
        campaign_id="campaign-1",
        status=OperationalActivityStatus.SUPERSEDED,
        freshness=OperationalFreshness.UNKNOWN,
        evidence_count=0,
        duration_ms=10,
        reason_codes=("state_write_conflict",),
        observed_at=datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert activity.result_state is OperationalActivityResultState.NOT_RECORDED
    assert activity.result_count is None


def test_failed_observation_does_not_claim_pre_failure_count() -> None:
    spec = ObservationSourceSpec(
        source_id="activity-log",
        domain=ObservationDomain.ACTIVITY_LOG,
        owner_agent="Huginn",
        interval_seconds=60,
        lookback_seconds=300,
        timeout_seconds=1,
        max_targets=16,
        max_results=100,
        max_output_bytes=64_000,
        required=True,
    )
    activity = _activity(
        spec=spec,
        campaign_id="campaign-2",
        status=OperationalActivityStatus.FAILED,
        freshness=OperationalFreshness.UNAVAILABLE,
        evidence_count=5,
        duration_ms=10,
        reason_codes=("provider_failure",),
        observed_at=datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert activity.result_state is OperationalActivityResultState.UNAVAILABLE
    assert activity.evidence_count == 0
    assert activity.result_count is None
