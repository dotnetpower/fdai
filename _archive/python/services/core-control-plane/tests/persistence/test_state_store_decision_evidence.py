"""Durable decision-evidence admission persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.delivery.persistence.state_store_decision_evidence import (
    DecisionEvidenceAdmissionRecordError,
    StateStoreDecisionEvidenceAdmissionProvider,
    StateStoreDecisionEvidenceAdmissionRecorder,
    decision_evidence_state_key,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRequirement,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest

_NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
_DIGESTS = tuple("sha256:" + char * 64 for char in "abcdef0")


def _receipt(**overrides: object) -> DecisionCriticalEvidenceReceipt:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "authority_class": "provider_observation",
        "source_identity": "principal:inventory-reader",
        "authentication_evidence_digest": _DIGESTS[0],
        "scope_digest": _DIGESTS[1],
        "purpose_id": "readiness",
        "producer_id": "inventory-observer",
        "producer_version": "1.0.0",
        "method_id": "resource-health-query",
        "method_version": "1.0.0",
        "source_revision": "api-version:2026-01-01",
        "evidence_digest": _DIGESTS[2],
        "provenance_digest": _DIGESTS[3],
        "event_at": _NOW,
        "evidence_cutoff": _NOW + timedelta(minutes=1),
        "recorded_at": _NOW + timedelta(minutes=2),
        "fresh_until": _NOW + timedelta(minutes=10),
        "freshness_policy_id": "readiness-eight-minute",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": _DIGESTS[4],
        "freshness_ceiling_seconds": 540,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": _DIGESTS[5],
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": _DIGESTS[6],
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    values.update(overrides)
    return DecisionCriticalEvidenceReceipt.model_validate(
        {
            **values,
            "receipt_digest": decision_critical_evidence_receipt_digest(**values),
        }
    )


def _requirement() -> LiveEvidenceClaimRequirement:
    return LiveEvidenceClaimRequirement(
        allowed_authority_classes=("provider_observation",),
        allowed_source_identities=("principal:inventory-reader",),
        scope_digest=_DIGESTS[1],
        purpose_id="readiness",
        producer_id="inventory-observer",
        producer_version="1.0.0",
        method_id="resource-health-query",
        method_version="1.0.0",
        source_revision="api-version:2026-01-01",
        freshness_policy_digest=_DIGESTS[4],
        freshness_ceiling_seconds=540,
        minimum_completeness_basis_points=10_000,
    )


def _bundle(
    receipt: DecisionCriticalEvidenceReceipt,
    *,
    verifier_id: str = "azure.readback",
) -> DecisionEvidenceVerificationBundle:
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        DecisionEvidenceVerificationProof(
            kind=kind,
            receipt_digest=receipt.receipt_digest,
            subject_digest=subject,
            proof_digest="sha256:" + str(index) * 64,
            verifier_id=verifier_id,
            verifier_version="1.0.0",
            trust_anchor_id="azure:managed-identity",
            issued_at=_NOW + timedelta(minutes=2),
            valid_until=_NOW + timedelta(minutes=8),
        )
        for index, (kind, subject) in enumerate(subjects.items(), start=1)
    )
    return DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id=verifier_id,
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
        verified_at=_NOW + timedelta(minutes=2),
        valid_until=_NOW + timedelta(minutes=8),
        proofs=proofs,
    )


class _Verifier:
    def __init__(self, bundle: DecisionEvidenceVerificationBundle) -> None:
        self._bundle = bundle

    async def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationBundle:
        del receipt, trust_anchor_id
        return self._bundle


async def _eligible_result(
    receipt: DecisionCriticalEvidenceReceipt,
):
    bundle = _bundle(receipt)
    gate = DecisionEvidenceReadinessGate(
        registry=DecisionEvidenceVerifierRegistry(
            (
                DecisionEvidenceVerifierBinding(
                    authority_class=receipt.authority_class,
                    method_id=receipt.method_id,
                    verifier_id=bundle.verifier_id,
                    verifier_version=bundle.verifier_version,
                    trust_anchor_id=bundle.trust_anchor_id,
                    verifier=_Verifier(bundle),
                ),
            )
        )
    )
    return await gate.evaluate(
        receipt,
        _requirement(),
        evaluated_at=_NOW + timedelta(minutes=3),
    )


async def test_verified_admission_is_retained_and_resolved() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    result = await _eligible_result(receipt)

    created = await StateStoreDecisionEvidenceAdmissionRecorder(
        store=store,
        clock=lambda: _NOW + timedelta(minutes=3),
    ).retain(receipt, result)
    admission = await StateStoreDecisionEvidenceAdmissionProvider(
        store=store,
        clock=lambda: _NOW + timedelta(minutes=4),
    ).admit(
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
    )

    assert created is True
    assert admission == result.admission
    assert await store.verify_chain() is True


async def test_identical_redelivery_is_idempotent() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    result = await _eligible_result(receipt)
    recorder = StateStoreDecisionEvidenceAdmissionRecorder(store=store)

    assert await recorder.retain(receipt, result) is True
    assert await recorder.retain(receipt, result) is False


async def test_rejected_evidence_is_not_retained() -> None:
    store = InMemoryStateStore()
    receipt = _receipt(synthetic=True)
    result = await _eligible_result(receipt)

    assert result.eligible is False
    with pytest.raises(ValueError, match="only eligible"):
        await StateStoreDecisionEvidenceAdmissionRecorder(store=store).retain(receipt, result)


async def test_expired_admission_returns_no_result() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    result = await _eligible_result(receipt)
    await StateStoreDecisionEvidenceAdmissionRecorder(store=store).retain(receipt, result)

    admission = await StateStoreDecisionEvidenceAdmissionProvider(
        store=store,
        clock=lambda: _NOW + timedelta(minutes=9),
    ).admit(
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
    )

    assert admission is None


async def test_tampered_record_fails_closed() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    result = await _eligible_result(receipt)
    await StateStoreDecisionEvidenceAdmissionRecorder(store=store).retain(receipt, result)
    key = decision_evidence_state_key(
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
    )
    raw = await store.read_state(key)
    assert raw is not None
    tampered = dict(raw)
    tampered["schema_version"] = "fdai.decision-evidence-admission.v0"
    await store.write_state(key, tampered)

    with pytest.raises(DecisionEvidenceAdmissionRecordError, match="shape"):
        await StateStoreDecisionEvidenceAdmissionProvider(store=store).admit(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        )


async def test_unknown_admission_field_fails_closed() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    result = await _eligible_result(receipt)
    await StateStoreDecisionEvidenceAdmissionRecorder(store=store).retain(receipt, result)
    key = decision_evidence_state_key(
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
    )
    raw = await store.read_state(key)
    assert raw is not None
    tampered = dict(raw)
    admission = dict(tampered["admission"])
    admission["unexpected_authority"] = True
    body = {name: value for name, value in tampered.items() if name != "record_digest"}
    body["admission"] = admission
    tampered.update(body)
    tampered["record_digest"] = content_digest(body)
    await store.write_state(key, tampered)

    with pytest.raises(DecisionEvidenceAdmissionRecordError, match="content is invalid"):
        await StateStoreDecisionEvidenceAdmissionProvider(store=store).admit(
            evidence_digest=receipt.evidence_digest,
            scope_digest=receipt.scope_digest,
            purpose_id=receipt.purpose_id,
            source_revision=receipt.source_revision,
        )


async def test_conflicting_redelivery_fails_closed() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    result = await _eligible_result(receipt)
    recorder = StateStoreDecisionEvidenceAdmissionRecorder(store=store)
    await recorder.retain(receipt, result)
    key = decision_evidence_state_key(
        evidence_digest=receipt.evidence_digest,
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        source_revision=receipt.source_revision,
    )
    raw = await store.read_state(key)
    assert raw is not None
    conflicting = dict(raw)
    body = {name: value for name, value in raw.items() if name != "record_digest"}
    body["lookup_digest"] = "sha256:" + "f" * 64
    conflicting.update(body)
    conflicting["record_digest"] = content_digest(body)
    await store.write_state(key, conflicting)

    with pytest.raises(DecisionEvidenceAdmissionRecordError, match="conflicting"):
        await recorder.retain(receipt, result)
