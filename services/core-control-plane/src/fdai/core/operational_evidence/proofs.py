"""Receipt and five-proof bundle construction from registry entries and verifier readback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import OperationalEvidenceIssuanceRequest

from .readback.base import ReadbackFacts
from .revision_history import RegistryPins
from .trust_registry import PurposeTrust, VerifierEntry


def build_receipt(
    request: OperationalEvidenceIssuanceRequest,
    entry: PurposeTrust,
    facts: ReadbackFacts,
    pins: RegistryPins,
    *,
    producer_id: str,
    recorded_at: datetime,
) -> DecisionCriticalEvidenceReceipt:
    lookup = request.lookup
    cutoff = _aware(facts.evidence_cutoff)
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "authority_class": entry.authority_class,
        "source_identity": facts.source_identity,
        "authentication_evidence_digest": content_digest(
            {
                "facts": dict(facts.authentication),
                "grant_registry_pin": pins.grant_pin,
                "matched_grants": sorted(set(facts.matched_grants)),
            }
        ),
        "scope_digest": lookup.scope_digest,
        "purpose_id": lookup.purpose_id,
        "producer_id": producer_id,
        "producer_version": request.producer_version,
        "method_id": entry.method_id,
        "method_version": entry.method_version,
        "source_revision": lookup.source_revision,
        "evidence_digest": lookup.evidence_digest,
        "provenance_digest": content_digest(
            {
                "facts": dict(facts.provenance),
                "grant_registry_pin": pins.grant_pin,
                "locator_digest": content_digest(request.locator.model_dump(mode="json")),
                "trust_registry_pin": pins.trust_pin,
            }
        ),
        "event_at": _aware(facts.event_at),
        "evidence_cutoff": cutoff,
        "recorded_at": recorded_at,
        "fresh_until": cutoff + timedelta(seconds=entry.freshness.ceiling_seconds),
        "freshness_policy_id": entry.freshness.policy_id,
        "freshness_policy_version": entry.freshness.policy_version,
        "freshness_policy_digest": entry.freshness.digest,
        "freshness_ceiling_seconds": entry.freshness.ceiling_seconds,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": content_digest(dict(facts.completeness)),
        "conflict_status": "clear",
        "conflict_evidence_digest": content_digest(dict(facts.conflict)),
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    return DecisionCriticalEvidenceReceipt.model_validate(
        {**values, "receipt_digest": decision_critical_evidence_receipt_digest(**values)}
    )


def build_bundle(
    receipt: DecisionCriticalEvidenceReceipt,
    verifier: VerifierEntry,
    *,
    verified_at: datetime,
    valid_until: datetime,
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
            proof_digest=content_digest(
                {
                    "issued_at": verified_at.isoformat(),
                    "kind": kind.value,
                    "receipt_digest": receipt.receipt_digest,
                    "subject_digest": subject,
                    "trust_anchor_id": verifier.trust_anchor_id,
                    "verifier_id": verifier.verifier_id,
                    "verifier_version": verifier.verifier_version,
                }
            ),
            verifier_id=verifier.verifier_id,
            verifier_version=verifier.verifier_version,
            trust_anchor_id=verifier.trust_anchor_id,
            issued_at=verified_at,
            valid_until=valid_until,
        )
        for kind, subject in subjects.items()
    )
    return DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id=verifier.verifier_id,
        verifier_version=verifier.verifier_version,
        trust_anchor_id=verifier.trust_anchor_id,
        verified_at=verified_at,
        valid_until=valid_until,
        proofs=proofs,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("operational evidence time MUST include a timezone")
    return value.astimezone(UTC)


__all__ = ["build_bundle", "build_receipt"]
