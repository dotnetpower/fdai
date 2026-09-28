"""Operational evidence wire contracts and the token-free Operator authentication receipt."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.operational_evidence import (
    OPERATIONAL_EVIDENCE_PURPOSES,
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
    OperationalEvidenceRejectionRecord,
    OperationalEvidenceVerifierReadiness,
)
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)
from pydantic import ValidationError

_NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
_LOOKUP = {
    "evidence_digest": "sha256:" + "1" * 64,
    "scope_digest": "sha256:" + "2" * 64,
    "purpose_id": "operator-test-context-command",
    "source_revision": "policy:test-context:1",
}


def _rejection(**overrides: object) -> OperationalEvidenceRejectionRecord:
    values: dict[str, object] = {
        "attempt_id": "a" * 32,
        "lookup_digest": "sha256:" + "3" * 64,
        "purpose_id": "operator-test-context-command",
        "rejection_class": OperationalEvidenceRejectionClass.PARTIAL,
        "reason_codes": ("source_record_missing",),
        "trust_registry_pin": "sha256:" + "4" * 64,
        "grant_registry_pin": "sha256:" + "5" * 64,
        "verifier_id": "operational-evidence-verifier",
        "verifier_version": "1.0.0",
        "recorded_at": _NOW,
    }
    values.update(overrides)
    return OperationalEvidenceRejectionRecord.create(**values)  # type: ignore[arg-type]


def test_eleven_purposes_and_lookup_digest_match_the_admission_records() -> None:
    assert len(OPERATIONAL_EVIDENCE_PURPOSES) == 11
    lookup = OperationalEvidenceLookup(**_LOOKUP)
    assert lookup.lookup_digest.startswith("sha256:")
    with pytest.raises(ValidationError):
        OperationalEvidenceLookup(**{**_LOOKUP, "purpose_id": "deployment-apply"})


def test_locator_is_coordinates_only_and_bound_to_its_purpose() -> None:
    locator = OperationalEvidenceLocator(
        purpose_id="operator-test-context-command", coordinates={"idempotency_key": "k"}
    )
    assert locator.coordinate("idempotency_key") == "k"
    for coordinates in ({}, {"observed_value": "80"}, {"idempotency_key": "a\nb"}):
        with pytest.raises(ValidationError):
            OperationalEvidenceLocator(
                purpose_id="operator-test-context-command", coordinates=coordinates
            )
    with pytest.raises(ValidationError, match="locator purpose mismatches"):
        OperationalEvidenceIssuanceRequest(
            attempt_id="b" * 32,
            lookup=OperationalEvidenceLookup(**_LOOKUP),
            locator=OperationalEvidenceLocator(
                purpose_id="case-history-read", coordinates={"principal_ref": "p"}
            ),
            producer_id="core-control-plane",
            producer_version="1.0.0",
            requested_at=_NOW,
        )


def test_response_is_content_free_and_never_grants_authority() -> None:
    unavailable = OperationalEvidenceIssuanceResponse(
        attempt_id="c" * 32,
        lookup_digest="sha256:" + "6" * 64,
        status=OperationalEvidenceIssuanceStatus.UNAVAILABLE,
    )
    assert unavailable.record_digest is None
    with pytest.raises(ValidationError):
        OperationalEvidenceIssuanceResponse(
            attempt_id="c" * 32,
            lookup_digest="sha256:" + "6" * 64,
            status=OperationalEvidenceIssuanceStatus.ISSUED,
        )
    with pytest.raises(ValidationError):
        OperationalEvidenceIssuanceResponse.model_validate(
            {**unavailable.model_dump(mode="json"), "execution_authority": True}
        )


def test_rejection_record_has_a_fixed_sixty_second_attempt_window() -> None:
    record = _rejection()
    assert record.valid_until - record.recorded_at == timedelta(seconds=60)
    assert record.current_at(_NOW + timedelta(seconds=59))
    assert not record.current_at(_NOW + timedelta(seconds=60))
    tampered = {**record.model_dump(mode="json"), "reason_codes": ["other"]}
    with pytest.raises(ValidationError, match="digest mismatched"):
        OperationalEvidenceRejectionRecord.model_validate(tampered)
    with pytest.raises(ValidationError, match="conflict digests"):
        _rejection(rejection_class=OperationalEvidenceRejectionClass.CONFLICTING)
    conflicting = _rejection(
        rejection_class=OperationalEvidenceRejectionClass.CONFLICTING,
        conflict_evidence_digests=("sha256:" + "7" * 64,),
    )
    assert conflicting.conflict_evidence_digests == ("sha256:" + "7" * 64,)


def _receipt(**overrides: object) -> OperatorAuthenticationReceipt:
    values: dict[str, object] = {
        "evidence_class": OperatorAuthenticationEvidenceClass.LIVE,
        "issuer": "https://issuer.example.invalid/v2.0",
        "audience": "api://fdai-operator.example.invalid",
        "tenant_digest": tenant_digest("00000000-0000-0000-0000-000000000000"),
        "subject_id": "00000000-0000-0000-0000-000000000011",
        "principal_kind": "human",
        "groups": ["00000000-0000-0000-0000-000000000002", "00000000-0000-0000-0000-000000000001"],
        "token_id_digest": token_id_digest("token-identifier"),
        "issued_at": _NOW,
        "expires_at": _NOW + timedelta(hours=1),
        "roles": ["Contributor"],
        "role_mapping_revision": role_mapping_revision({"Contributor": "group"}),
    }
    values.update(overrides)
    return OperatorAuthenticationReceipt.create(**values)


def test_authentication_receipt_keeps_exact_groups_and_no_token() -> None:
    receipt = _receipt()
    assert receipt.groups == (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )
    assert receipt.group_overage is False and receipt.token_retained is False
    assert receipt.valid_at(_NOW + timedelta(minutes=30))
    assert not receipt.valid_at(_NOW + timedelta(hours=1))
    assert "token-identifier" not in receipt.model_dump_json()
    for invalid in (
        {"expires_at": _NOW + timedelta(hours=25)},
        {"principal_kind": "workload"},
        {"issuer": LOCAL_LOOPBACK_ISSUER},
        {"roles": ["Administrator"]},
    ):
        with pytest.raises(ValidationError):
            _receipt(**invalid)
    local = _receipt(
        evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
        issuer=LOCAL_LOOPBACK_ISSUER,
        audience=LOCAL_LOOPBACK_ISSUER,
    )
    assert local.evidence_class is OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK


def _readiness(**overrides: object) -> OperationalEvidenceVerifierReadiness:
    values: dict[str, object] = {
        "state": "ready",
        "verifier_id": "operational-evidence-verifier",
        "verifier_version": "1.0.0",
        "trust_registry_pin": "sha256:" + "4" * 64,
        "grant_registry_pin": "sha256:" + "5" * 64,
        "bound_purposes": ["operator-test-context-command", "test-context-transition"],
        "source_health": {"operator-service.test-context-outbox": "healthy"},
        "probed_at": _NOW,
    }
    values.update(overrides)
    return OperationalEvidenceVerifierReadiness.model_validate(values)


def test_verifier_readiness_is_content_free_and_grants_no_authority() -> None:
    ready = _readiness()
    assert ready.execution_authority is False and ready.promotion_authority is False
    assert ready.model_validate_json(ready.model_dump_json()) == ready
    blocked = _readiness(state="self_verified", reasons=["foreign_insert_grant"])
    assert blocked.reasons == ("foreign_insert_grant",)
    assert _readiness(probed_at=None).probed_at is None
    for invalid in (
        {"state": "self_verified"},
        {"reasons": ["not_probed"]},
        {"state": "unavailable", "reasons": ["b_reason", "a_reason"]},
        {"state": "unavailable", "reasons": ["OperationalError"]},
        {"bound_purposes": ["test-context-transition", "operator-test-context-command"]},
        {"bound_purposes": ["unregistered-purpose"]},
        {"source_health": {"operator-service.test-context-outbox": "degraded"}},
        {"source_health": {f"source-{index}": "healthy" for index in range(33)}},
        {"probed_at": _NOW.replace(tzinfo=None)},
        {"execution_authority": True},
        {"promotion_authority": True},
        {"unexpected": "field"},
    ):
        with pytest.raises(ValidationError):
            _readiness(**invalid)
