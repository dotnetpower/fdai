from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.readiness import (
    AuthorityCeiling,
    DetectionObservationStatus,
    DetectionReadinessDecision,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    reduce_detection_readiness,
)

_NOW = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
_RESOURCE = "cluster/example"


def _observation(
    dimension: DetectionReadinessDimension,
    *,
    status: DetectionObservationStatus = DetectionObservationStatus.PASSED,
    expires_at: datetime | None = None,
) -> DetectionReadinessObservation:
    return DetectionReadinessObservation(
        resource_ref=_RESOURCE,
        dimension=dimension,
        status=status,
        observed_at=_NOW - timedelta(minutes=1),
        expires_at=expires_at or _NOW + timedelta(minutes=4),
        source="azure.monitor",
        evidence_digest="a" * 64,
        detail_code=None if status is DetectionObservationStatus.PASSED else "probe_failed",
    )


def test_all_required_dimensions_are_ready_without_raising_deployment_ceiling() -> None:
    snapshot = reduce_detection_readiness(
        tuple(_observation(dimension) for dimension in DetectionReadinessDimension),
        resource_ref=_RESOURCE,
        generated_at=_NOW,
        deployment_ceiling=AuthorityCeiling.HUMAN_APPROVAL,
    )

    assert snapshot.decision is DetectionReadinessDecision.READY
    assert snapshot.authority_ceiling is AuthorityCeiling.HUMAN_APPROVAL
    assert snapshot.missing_dimensions == ()


def test_missing_dimension_is_partial_and_caps_authority_at_shadow() -> None:
    snapshot = reduce_detection_readiness(
        (_observation(DetectionReadinessDimension.DISCOVERED),),
        resource_ref=_RESOURCE,
        generated_at=_NOW,
    )

    assert snapshot.decision is DetectionReadinessDecision.PARTIAL
    assert snapshot.authority_ceiling is AuthorityCeiling.SHADOW
    assert DetectionReadinessDimension.TELEMETRY_OBSERVED in snapshot.missing_dimensions


def test_stale_evidence_takes_precedence_over_missing_dimensions() -> None:
    snapshot = reduce_detection_readiness(
        (
            _observation(
                DetectionReadinessDimension.DISCOVERED,
                expires_at=_NOW,
            ),
        ),
        resource_ref=_RESOURCE,
        generated_at=_NOW,
    )

    assert snapshot.decision is DetectionReadinessDecision.STALE
    assert snapshot.stale_dimensions == (DetectionReadinessDimension.DISCOVERED,)


def test_unauthorized_evidence_fails_closed() -> None:
    snapshot = reduce_detection_readiness(
        (
            _observation(
                DetectionReadinessDimension.COLLECTOR_CONFIGURED,
                status=DetectionObservationStatus.UNAUTHORIZED,
            ),
        ),
        resource_ref=_RESOURCE,
        generated_at=_NOW,
    )

    assert snapshot.decision is DetectionReadinessDecision.UNAUTHORIZED
    assert snapshot.authority_ceiling is AuthorityCeiling.SHADOW


def test_duplicate_dimension_is_rejected() -> None:
    observation = _observation(DetectionReadinessDimension.DISCOVERED)
    with pytest.raises(ValueError, match="unique by dimension"):
        reduce_detection_readiness(
            (observation, observation),
            resource_ref=_RESOURCE,
            generated_at=_NOW,
        )
