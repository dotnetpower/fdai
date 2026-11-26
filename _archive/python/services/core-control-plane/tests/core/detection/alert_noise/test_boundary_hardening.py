"""Round 1: reject noncanonical boundary values and half-specified treatment axes."""

from datetime import datetime

import pytest
from fdai_service_contracts.alert_noise import AlertEvidence, Audience, EvidenceStamp
from fdai_service_contracts.alert_noise_plan import AlertTreatment
from pydantic import ValidationError


@pytest.mark.parametrize("value", [0, 1, "false", None, {}, []])
def test_evidence_authority_is_literal_false(evidence: AlertEvidence, value: object) -> None:
    record = evidence.model_dump(mode="json")
    record["execution_authority"] = value
    with pytest.raises(ValidationError):
        AlertEvidence.model_validate(record)


@pytest.mark.parametrize(
    "value", [0, 1.0, "2026-09-15", "2026-09-15T00:00:00", "2026-09-15T00:00:00-00:00"]
)
def test_numeric_and_ambiguous_timestamps_are_not_normalized(
    evidence: AlertEvidence,
    value: object,
) -> None:
    record = evidence.stamp.model_dump(mode="json")
    record["observed_at"] = value
    with pytest.raises(ValidationError):
        EvidenceStamp.model_validate(record)


@pytest.mark.parametrize("field", ["starts_at", "ends_at", "processing_rule_ref"])
def test_routing_rejects_each_foreign_field(field: str, now: datetime) -> None:
    record = {
        "kind": "routing",
        "target_ref": "rule:test",
        "remove_group_ref": "group:old",
        "replacement_group_ref": "group:new",
        field: now if field.endswith("_at") else "processing:test",
    }
    with pytest.raises(ValidationError):
        AlertTreatment.model_validate(record)


@pytest.mark.parametrize(
    "field", ["remove_group_ref", "replacement_group_ref", "starts_at", "ends_at"]
)
def test_evaluation_rejects_each_foreign_field(
    evidence: AlertEvidence,
    now: datetime,
    field: str,
) -> None:
    record = {
        "kind": "evaluation",
        "target_ref": "rule:test",
        "evaluation": evidence.rules[0].evaluation,
        field: now if field.endswith("_at") else "group:test",
    }
    with pytest.raises(ValidationError):
        AlertTreatment.model_validate(record)


def test_copied_models_are_revalidated_at_boundary(evidence: AlertEvidence) -> None:
    changed = evidence.model_copy(update={"execution_authority": True})
    with pytest.raises(ValidationError):
        AlertEvidence.model_validate(changed)


@pytest.mark.parametrize(
    "changes",
    [
        {"member_refs": ("principal:a", "principal:a")},
        {"potential_members": 1},
        {"potential_members": True},
    ],
)
def test_audience_count_and_identity_invariants(evidence: AlertEvidence, changes: dict) -> None:
    record = {**evidence.audiences[0].model_dump(), **changes}
    with pytest.raises(ValidationError):
        Audience.model_validate(record)
