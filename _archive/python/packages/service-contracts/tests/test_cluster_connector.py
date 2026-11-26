"""Admission boundaries for outbound cluster metadata; no live credentials or resources."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.cluster_connector import (
    ConnectorEvidence,
    ConnectorRegistration,
    ConnectorScope,
    ConnectorWork,
    connector_time,
)

NOW = datetime(2026, 9, 19, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def scope(**changes: object) -> ConnectorScope:
    return ConnectorScope.model_validate(
        {
            "deployment_ref": "deployment-example",
            "cluster_ref": "cluster-example",
            "connector_id": "observer-example",
            "enrollment_revision": 1,
            **changes,
        }
    )


def registration(**changes: object) -> ConnectorRegistration:
    return ConnectorRegistration.model_validate(
        {
            "scope": scope(),
            "principal_ref": "principal-example",
            "role": "observer",
            "namespaces": ("example",),
            "capabilities": ("diagnostic.read", "inventory.snapshot"),
            "valid_from": NOW - timedelta(minutes=1),
            "expires_at": NOW + timedelta(hours=1),
            **changes,
        }
    )


def evidence(**changes: object) -> ConnectorEvidence:
    return ConnectorEvidence.model_validate(
        {
            "scope": scope(),
            "capability": "inventory.snapshot",
            "stream_id": "stream-example",
            "sequence": 1,
            "observed_at": NOW,
            "producer_revision": DIGEST,
            "artifact_digest": DIGEST,
            "artifact_bytes": 128,
            "namespaces": ("example",),
            "complete": True,
            **changes,
        }
    )


def test_evidence_admission_and_wire_roundtrip() -> None:
    packet = evidence()
    packet.admit(registration(), principal_ref="principal-example", now=NOW, max_age_seconds=60)
    restored = ConnectorEvidence.model_validate_json(packet.model_dump_json())
    assert restored == packet
    assert restored.digest == packet.digest


@pytest.mark.parametrize(
    "changes",
    [
        {"revoked": True},
        {"principal_ref": "other"},
        {"expires_at": NOW},
        {"valid_from": NOW + timedelta(seconds=1)},
        {"scope": scope(cluster_ref="other")},
        {"scope": scope(enrollment_revision=2)},
        {"namespaces": ("other",)},
        {"capabilities": ("diagnostic.read",)},
    ],
)
def test_evidence_rejects_unadmitted_registration(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        evidence().admit(
            registration(**changes), principal_ref="principal-example", now=NOW, max_age_seconds=60
        )


@pytest.mark.parametrize(
    "value", [NOW.replace(tzinfo=None), "2026-09-19", 123, True, None, "invalid"]
)
def test_rejects_ambiguous_clocks(value: object) -> None:
    with pytest.raises(ValueError):
        connector_time(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"sequence": True},
        {"sequence": "1"},
        {"artifact_bytes": 8_388_609},
        {"execution_authority": 0},
        {"execution_authority": True},
        {"complete": False},
        {"complete": True, "limitations": ("coverage_gap",)},
        {"namespaces": ("example", "example")},
        {"namespaces": ("*",)},
        {"stream_id": "stream\nexample"},
        {"unknown": True},
    ],
)
def test_rejects_malformed_evidence(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        evidence(**changes)


@pytest.mark.parametrize("age", [-1, 60, 61])
def test_freshness_boundary(age: int) -> None:
    with pytest.raises(ValueError):
        evidence(observed_at=NOW - timedelta(seconds=age)).admit(
            registration(),
            principal_ref="principal-example",
            now=NOW,
            max_age_seconds=60,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "executor"},
        {"capabilities": ("governed.execute",)},
        {"role": "executor", "capabilities": ("diagnostic.read", "governed.execute")},
        {"capabilities": ("inventory.snapshot", "diagnostic.read")},
    ],
)
def test_observer_and_executor_roles_are_separate(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        registration(**changes)


def test_partial_evidence_and_timezone_normalization() -> None:
    packet = evidence(
        complete=False, limitations=("coverage_gap",), observed_at="2026-09-19T09:00:00+09:00"
    )
    assert packet.observed_at == NOW
    packet.admit(registration(), principal_ref="principal-example", now=NOW, max_age_seconds=60)
    assert packet.digest != evidence().digest


def test_work_admission_does_not_accept_expiry_or_foreign_namespace() -> None:
    record = {
        "scope": scope(),
        "work_id": "work-example",
        "correlation_id": "correlation-example",
        "capability": "diagnostic.read",
        "namespace": "example",
        "target_uid": "uid-example",
        "target_revision": "42",
        "artifact_digest": DIGEST,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=1),
        "idempotency_key": "key-example",
    }
    work = ConnectorWork.model_validate(record)
    work.admit(registration(), principal_ref="principal-example", now=NOW)
    assert ConnectorWork.model_validate_json(work.model_dump_json()).digest == work.digest
    with pytest.raises(ValueError):
        work.admit(registration(), principal_ref="principal-example", now=work.expires_at)
    with pytest.raises(ValueError):
        work.admit(registration(namespaces=("other",)), principal_ref="principal-example", now=NOW)
    with pytest.raises(ValidationError):
        ConnectorWork.model_validate({**record, "expires_at": NOW + timedelta(hours=1)})


@pytest.mark.parametrize(
    "value", ["https://user:password@example.com", "cluster?token=value", "cluster#fragment"]
)
def test_cluster_reference_cannot_embed_credentials(value: str) -> None:
    with pytest.raises(ValidationError):
        scope(cluster_ref=value)


@pytest.mark.parametrize("changes", [{"sequence": 2**63}, {"sequence": 0}])
def test_sequence_fits_durable_revision(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        evidence(**changes)


def test_registered_schema_applies_semantic_validation() -> None:
    from fdai_service_contracts.schema import (
        ContractValidationError,
        JsonSchemaContractValidator,
        PackageResourceSchemaRegistry,
    )

    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    validator.validate("cluster-connector-evidence", evidence().model_dump(mode="json"))
    malformed = evidence().model_dump(mode="json")
    malformed["complete"] = False
    with pytest.raises(ContractValidationError):
        validator.validate("cluster-connector-evidence", malformed)
