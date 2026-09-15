"""Boundary rejection and immutable contract checks for alert-quality evidence."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.alert_noise import Audience, Evaluation, EvidenceStamp
from fdai_service_contracts.alert_noise_plan import AlertTreatment


def test_audience_rejects_unknown_extra_and_raw_address() -> None:
    with pytest.raises(ValidationError):
        Audience(
            ref="person@example.com",
            kind="direct",
            revision="sha256:" + "a" * 64,
            coverage="partial",
        )


def test_complete_membership_requires_exact_count() -> None:
    with pytest.raises(ValidationError, match="complete audience"):
        Audience(
            ref="audience:example",
            kind="group",
            revision="sha256:" + "a" * 64,
            coverage="complete",
            member_refs=("person:one",),
            potential_members=2,
        )


def test_evidence_requires_aware_ordered_time() -> None:
    now = datetime(2026, 9, 14, tzinfo=UTC)
    with pytest.raises(ValidationError):
        EvidenceStamp(
            source="source:one",
            tenant_ref="tenant:one",
            scope_ref="scope:one",
            revision="sha256:" + "a" * 64,
            observed_at=now,
            recorded_at=now,
            valid_until=now - timedelta(seconds=1),
            coverage="complete",
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "80", True])
def test_evaluation_rejects_nonfinite_and_coercion(value: object) -> None:
    with pytest.raises(ValidationError):
        Evaluation.model_validate(
            {
                "metric_ref": "metric:cpu",
                "operator": "above",
                "threshold": value,
                "window_seconds": 300,
                "frequency_seconds": 60,
                "aggregation": "average",
            }
        )


def test_treatment_requires_single_axis() -> None:
    with pytest.raises(ValidationError):
        AlertTreatment(kind="routing", target_ref="rule:one")
