"""Durable decision-evidence admissions over the shared StateStore."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessResult
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    resolve_current_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore

_RECORD_SCHEMA = "fdai.decision-evidence-admission.v1"
_STATE_PREFIX = "decision-evidence-admission:v1:"
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "lookup_digest",
        "receipt",
        "verification_bundle",
        "admission",
        "record_digest",
    }
)
_ADMISSION_FIELDS = frozenset(
    {
        "receipt_digest",
        "verification_bundle_digest",
        "evidence_digest",
        "scope_digest",
        "purpose_id",
        "source_revision",
        "verified_at",
        "valid_until",
        "execution_authority",
        "promotion_authority",
    }
)


class DecisionEvidenceAdmissionRecordError(RuntimeError):
    """A retained admission is malformed, conflicting, or no longer trustworthy."""


@dataclass(frozen=True, slots=True)
class RetainedDecisionEvidence:
    """Canonical receipt, independent proof bundle, and derived admission."""

    receipt: DecisionCriticalEvidenceReceipt
    verification_bundle: DecisionEvidenceVerificationBundle
    admission: DecisionEvidenceAdmission


def decision_evidence_lookup_digest(
    *,
    evidence_digest: str,
    scope_digest: str,
    purpose_id: str,
    source_revision: str,
) -> str:
    """Return the content address for one exact admission request."""

    return content_digest(
        {
            "evidence_digest": evidence_digest,
            "purpose_id": purpose_id,
            "scope_digest": scope_digest,
            "source_revision": source_revision,
        }
    )


def decision_evidence_state_key(
    *,
    evidence_digest: str,
    scope_digest: str,
    purpose_id: str,
    source_revision: str,
) -> str:
    """Return the StateStore key without exposing source or scope identifiers."""

    lookup_digest = decision_evidence_lookup_digest(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=purpose_id,
        source_revision=source_revision,
    )
    return _STATE_PREFIX + lookup_digest.removeprefix("sha256:")


class StateStoreDecisionEvidenceAdmissionRecorder:
    """Persist only independently verified admissions with one atomic audit."""

    def __init__(
        self,
        *,
        store: StateStore,
        recorder_id: str = "decision-evidence-admission-recorder",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not recorder_id.strip() or len(recorder_id) > 128:
            raise ValueError("decision evidence recorder_id MUST be bounded non-empty text")
        self._store = store
        self._recorder_id = recorder_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def retain(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        result: DecisionEvidenceReadinessResult,
    ) -> bool:
        """Write one verified record once; reject a conflicting redelivery."""

        if not result.eligible or result.admission is None or result.verification_bundle is None:
            raise ValueError("only eligible decision evidence can be retained")
        retained = RetainedDecisionEvidence(
            receipt=receipt,
            verification_bundle=result.verification_bundle,
            admission=result.admission,
        )
        _validate_relations(retained)
        value = decision_evidence_record_mapping(retained)
        key = decision_evidence_state_key(
            evidence_digest=retained.admission.evidence_digest,
            scope_digest=retained.admission.scope_digest,
            purpose_id=retained.admission.purpose_id,
            source_revision=retained.admission.source_revision,
        )
        recorded_at = _aware_utc(self._clock())
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "decision-evidence.admission-retained",
                "event_id": value["record_digest"],
                "idempotency_key": value["record_digest"],
                "actor_identity": self._recorder_id,
                "timestamp": recorded_at.isoformat(),
                "decision": "verified",
                "outcome": "retained",
                "mode": "shadow",
                "receipt_digest": retained.receipt.receipt_digest,
                "verification_bundle_digest": retained.verification_bundle.bundle_digest,
                "record_digest": value["record_digest"],
                "execution_authority": False,
                "promotion_authority": False,
            },
        )
        if created:
            return True
        existing = await self._store.read_state(key)
        if existing != value:
            raise DecisionEvidenceAdmissionRecordError(
                "decision evidence admission key has conflicting retained content"
            )
        return False


class StateStoreDecisionEvidenceAdmissionProvider:
    """Resolve exact, current admissions from validated immutable records."""

    def __init__(
        self,
        *,
        store: StateStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        """Return a matching unexpired admission, or no admission when absent."""

        key = decision_evidence_state_key(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
        )
        raw = await self._store.read_state(key)
        if raw is None:
            return None
        retained = parse_decision_evidence_record(raw)
        try:
            return resolve_current_decision_evidence_admission(
                retained.admission,
                expected_evidence_digest=evidence_digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=purpose_id,
                expected_source_revision=source_revision,
                evaluated_at=_aware_utc(self._clock()),
            )
        except ValueError as exc:
            raise DecisionEvidenceAdmissionRecordError(
                "retained decision evidence does not match its content-addressed lookup"
            ) from exc


def decision_evidence_record_mapping(
    retained: RetainedDecisionEvidence,
) -> dict[str, object]:
    """Return the canonical immutable record retained by durable providers."""

    admission = retained.admission
    lookup_digest = decision_evidence_lookup_digest(
        evidence_digest=admission.evidence_digest,
        scope_digest=admission.scope_digest,
        purpose_id=admission.purpose_id,
        source_revision=admission.source_revision,
    )
    body: dict[str, object] = {
        "schema_version": _RECORD_SCHEMA,
        "lookup_digest": lookup_digest,
        "receipt": retained.receipt.model_dump(mode="json"),
        "verification_bundle": retained.verification_bundle.model_dump(mode="json"),
        "admission": admission.to_mapping(),
    }
    return {**body, "record_digest": content_digest(body)}


def parse_decision_evidence_record(raw: Mapping[str, Any]) -> RetainedDecisionEvidence:
    """Parse and cross-check one retained admission record."""

    if set(raw) != _RECORD_FIELDS or raw.get("schema_version") != _RECORD_SCHEMA:
        raise DecisionEvidenceAdmissionRecordError(
            "retained decision evidence record shape is invalid"
        )
    record_digest = _required_digest(raw, "record_digest")
    body = {key: value for key, value in raw.items() if key != "record_digest"}
    if content_digest(body) != record_digest:
        raise DecisionEvidenceAdmissionRecordError(
            "retained decision evidence record digest mismatched"
        )
    try:
        receipt = DecisionCriticalEvidenceReceipt.model_validate(_required_mapping(raw, "receipt"))
        bundle = DecisionEvidenceVerificationBundle.model_validate(
            _required_mapping(raw, "verification_bundle")
        )
        admission = _admission_from_mapping(_required_mapping(raw, "admission"))
    except (TypeError, ValueError) as exc:
        raise DecisionEvidenceAdmissionRecordError(
            "retained decision evidence record content is invalid"
        ) from exc
    retained = RetainedDecisionEvidence(
        receipt=receipt,
        verification_bundle=bundle,
        admission=admission,
    )
    _validate_relations(retained)
    expected_lookup = decision_evidence_lookup_digest(
        evidence_digest=admission.evidence_digest,
        scope_digest=admission.scope_digest,
        purpose_id=admission.purpose_id,
        source_revision=admission.source_revision,
    )
    if raw.get("lookup_digest") != expected_lookup:
        raise DecisionEvidenceAdmissionRecordError(
            "retained decision evidence lookup digest mismatched"
        )
    return retained


def _validate_relations(retained: RetainedDecisionEvidence) -> None:
    receipt = retained.receipt
    bundle = retained.verification_bundle
    admission = retained.admission
    expected_subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    actual_subjects = {proof.kind: proof.subject_digest for proof in bundle.proofs}
    if (
        bundle.receipt_digest != receipt.receipt_digest
        or admission.receipt_digest != receipt.receipt_digest
        or admission.verification_bundle_digest != bundle.bundle_digest
        or admission.evidence_digest != receipt.evidence_digest
        or admission.scope_digest != receipt.scope_digest
        or admission.purpose_id != receipt.purpose_id
        or admission.source_revision != receipt.source_revision
        or admission.verified_at != bundle.verified_at
        or admission.valid_until != bundle.valid_until
        or actual_subjects != expected_subjects
        or bundle.verifier_id in {receipt.source_identity, receipt.producer_id}
    ):
        raise DecisionEvidenceAdmissionRecordError(
            "decision evidence receipt, verification bundle, and admission do not agree"
        )


def _admission_from_mapping(raw: Mapping[str, Any]) -> DecisionEvidenceAdmission:
    if set(raw) != _ADMISSION_FIELDS:
        raise ValueError("retained decision evidence admission shape is invalid")
    if raw.get("execution_authority") is not False or raw.get("promotion_authority") is not False:
        raise ValueError("retained decision evidence admission cannot grant authority")
    return DecisionEvidenceAdmission(
        receipt_digest=_required_digest(raw, "receipt_digest"),
        verification_bundle_digest=_required_digest(raw, "verification_bundle_digest"),
        evidence_digest=_required_digest(raw, "evidence_digest"),
        scope_digest=_required_digest(raw, "scope_digest"),
        purpose_id=_required_text(raw, "purpose_id"),
        source_revision=_required_text(raw, "source_revision"),
        verified_at=_required_datetime(raw, "verified_at"),
        valid_until=_required_datetime(raw, "valid_until"),
    )


def _required_mapping(raw: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = raw.get(field)
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} MUST be an object")
    return value


def _required_digest(raw: Mapping[str, Any], field: str) -> str:
    value = _required_text(raw, field)
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be SHA-256")
    return value


def _required_text(raw: Mapping[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} MUST be non-empty text")
    return value


def _required_datetime(raw: Mapping[str, Any], field: str) -> datetime:
    return _aware_utc(datetime.fromisoformat(_required_text(raw, field)))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision evidence time MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "DecisionEvidenceAdmissionRecordError",
    "RetainedDecisionEvidence",
    "StateStoreDecisionEvidenceAdmissionProvider",
    "StateStoreDecisionEvidenceAdmissionRecorder",
    "decision_evidence_lookup_digest",
    "decision_evidence_record_mapping",
    "decision_evidence_state_key",
    "parse_decision_evidence_record",
]
