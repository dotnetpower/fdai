"""Boundary rejection and immutable contract checks for alert-quality evidence."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    Audience,
    Evaluation,
    EvidenceStamp,
    NoiseAssessment,
)
from fdai_service_contracts.alert_noise_base import AlertContractBase
from fdai_service_contracts.alert_noise_evaluation import (
    EvaluationReceipt,
    TemporalEvaluationScenarioSet,
)
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertTreatment
from fdai_service_contracts.alert_noise_wire import (
    SignedAlertCommand,
    SignedAlertReadiness,
    SignedAlertResult,
)
from fdai_service_contracts.schema import PackageResourceSchemaRegistry


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


@pytest.mark.parametrize(
    ("name", "model", "version"),
    [
        ("alert-noise-evidence", AlertEvidence, "1.0.0"),
        ("alert-noise-assessment", NoiseAssessment, "1.0.0"),
        ("alert-noise-plan", AlertChangePlan, "1.1.0"),
        ("alert-noise-command", SignedAlertCommand, "1.0.0"),
        ("alert-noise-result", SignedAlertResult, "1.1.0"),
        ("alert-noise-readiness", SignedAlertReadiness, "1.0.0"),
        ("alert-noise-evaluation", EvaluationReceipt, "1.0.0"),
        ("alert-noise-temporal-scenarios", TemporalEvaluationScenarioSet, "1.0.0"),
    ],
)
def test_registry_latest_schema_matches_active_alert_model(
    name: str, model: type[AlertContractBase], version: str
) -> None:
    expected = dict(model.model_json_schema())
    expected["$id"] = f"https://fdai.dev/service-contracts/{name}/{version}"

    assert PackageResourceSchemaRegistry().get(name) == expected
