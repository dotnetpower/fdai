"""Immutable A3-E revision identity and proof bindings."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Self

from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    canonical_json,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)
from fdai.core.standing_authority.record import (
    AuthorizationStatus,
    StandingAuthorization,
)


@dataclass(frozen=True, slots=True)
class AuthorizationProofBindings:
    """Approval and evidence proofs bound over one computed revision digest."""

    revision_id: str
    approval_claim_digest: str
    approvals_digest: str
    evidence_claim_digest: str
    evidence_verification_bundle_digest: str

    def __post_init__(self) -> None:
        require_digest("revision_id", self.revision_id)
        require_digest("approval_claim_digest", self.approval_claim_digest)
        require_digest("approvals_digest", self.approvals_digest)
        require_digest("evidence_claim_digest", self.evidence_claim_digest)
        require_digest(
            "evidence_verification_bundle_digest",
            self.evidence_verification_bundle_digest,
        )


@dataclass(frozen=True, slots=True)
class AuthorizationRevision:
    """One immutable authorization revision and its proof bindings."""

    family_id: str
    revision_id: str
    predecessor_revision_id: str | None
    issued_at: datetime
    terms_json: str
    document_json: str
    proof_bindings: AuthorizationProofBindings

    def __post_init__(self) -> None:
        require_text("family_id", self.family_id)
        require_digest("revision_id", self.revision_id)
        if self.predecessor_revision_id is not None:
            require_digest("predecessor_revision_id", self.predecessor_revision_id)
        require_aware("issued_at", self.issued_at)
        if self.proof_bindings.revision_id != self.revision_id:
            raise AuthorizationLifecycleError("proof bindings MUST target the exact revision")
        terms = _json_object(self.terms_json, name="terms_json")
        document = _json_object(self.document_json, name="document_json")
        if terms.get("family_id") != self.family_id:
            raise AuthorizationLifecycleError("revision terms family_id mismatch")
        if terms.get("predecessor_revision_id") != self.predecessor_revision_id:
            raise AuthorizationLifecycleError("revision predecessor mismatch")
        if content_digest(terms) != self.revision_id:
            raise AuthorizationLifecycleError("authorization revision digest mismatch")
        if document.get("authorization_revision") != self.revision_id:
            raise AuthorizationLifecycleError("authorization document revision mismatch")
        if document.get("status") != AuthorizationStatus.ACTIVE.value:
            raise AuthorizationLifecycleError("persisted authorization revision MUST be active")
        parsed = StandingAuthorization.from_mapping(document)
        if (
            _authorization_terms(
                parsed,
                family_id=self.family_id,
                predecessor_revision_id=self.predecessor_revision_id,
                issued_at=self.issued_at,
            )
            != terms
        ):
            raise AuthorizationLifecycleError("authorization document terms mismatch")
        if self.proof_bindings.approval_claim_digest != content_digest(
            {
                "revision_id": self.revision_id,
                "approvals": _approval_claims(parsed),
            }
        ):
            raise AuthorizationLifecycleError("authorization approval claims mismatch")
        if self.proof_bindings.evidence_claim_digest != content_digest(
            {
                "revision_id": self.revision_id,
                "evidence": _evidence_claims(parsed),
            }
        ):
            raise AuthorizationLifecycleError("authorization evidence claims mismatch")

    @classmethod
    def create(
        cls,
        *,
        family_id: str,
        predecessor_revision_id: str | None,
        issued_at: datetime,
        authorization: StandingAuthorization,
        approvals_digest: str,
        evidence_verification_bundle_digest: str,
        proof_subject_revision_id: str,
    ) -> Self:
        """Compute identity from terms, then bind approval and evidence proofs."""

        issued_at = aware_utc(issued_at)
        terms = _authorization_terms(
            authorization,
            family_id=family_id,
            predecessor_revision_id=predecessor_revision_id,
            issued_at=issued_at,
        )
        revision_id = content_digest(terms)
        effective = replace(
            authorization,
            authorization_revision=revision_id,
            status=AuthorizationStatus.ACTIVE,
        )
        return cls(
            family_id=family_id,
            revision_id=revision_id,
            predecessor_revision_id=predecessor_revision_id,
            issued_at=issued_at,
            terms_json=canonical_json(terms),
            document_json=canonical_json(_authorization_document(effective)),
            proof_bindings=AuthorizationProofBindings(
                revision_id=proof_subject_revision_id,
                approval_claim_digest=content_digest(
                    {
                        "revision_id": revision_id,
                        "approvals": _approval_claims(effective),
                    }
                ),
                approvals_digest=approvals_digest,
                evidence_claim_digest=content_digest(
                    {
                        "revision_id": revision_id,
                        "evidence": _evidence_claims(effective),
                    }
                ),
                evidence_verification_bundle_digest=evidence_verification_bundle_digest,
            ),
        )


def authorization_revision_id(
    *,
    family_id: str,
    predecessor_revision_id: str | None,
    issued_at: datetime,
    authorization: StandingAuthorization,
) -> str:
    """Compute the terms-only identity that approval and evidence proofs must sign."""

    return content_digest(
        _authorization_terms(
            authorization,
            family_id=family_id,
            predecessor_revision_id=predecessor_revision_id,
            issued_at=aware_utc(issued_at),
        )
    )


def _authorization_terms(
    authorization: StandingAuthorization,
    *,
    family_id: str,
    predecessor_revision_id: str | None,
    issued_at: datetime,
) -> dict[str, object]:
    return {
        "family_id": family_id,
        "issued_at": instant(issued_at),
        "predecessor_revision_id": predecessor_revision_id,
        "schema_version": authorization.schema_version,
        "authorization_id": authorization.id,
        "mode": authorization.mode.value,
        "requested_by": authorization.requested_by,
        "quorum_required": authorization.quorum_required,
        "valid_from": instant(authorization.valid_from),
        "valid_until": instant(authorization.valid_until),
        "service_ref": authorization.service_ref,
        "scope": {
            "level": authorization.scope.level.value,
            "value": authorization.scope.value,
        },
        "pins": {
            "policy_digest": authorization.pins.policy_digest,
            "target_revision": authorization.pins.target_revision,
            "action_type_versions": list(authorization.pins.action_type_versions),
            "evidence_revisions": list(authorization.pins.evidence_revisions),
        },
        "envelope": {
            "action_types": list(authorization.envelope.action_types),
            "max_blast_radius": authorization.envelope.max_blast_radius,
            "max_duration_seconds": authorization.envelope.max_duration_seconds,
            "reversible": authorization.envelope.reversible,
            "rollback_contract": authorization.envelope.rollback_contract,
            "stop_conditions": list(authorization.envelope.stop_conditions),
        },
        "incident_classes": list(authorization.incident_classes),
        "responders": {
            "primary": authorization.responders.primary,
            "backup": authorization.responders.backup,
            "confirmed_at": instant(authorization.responders.confirmed_at),
        },
    }


def _authorization_document(authorization: StandingAuthorization) -> dict[str, object]:
    return {
        "schema_version": authorization.schema_version,
        "id": authorization.id,
        "authorization_revision": authorization.authorization_revision,
        "status": authorization.status.value,
        "mode": authorization.mode.value,
        "requested_by": authorization.requested_by,
        "approvals": _approval_claims(authorization),
        "quorum_required": authorization.quorum_required,
        "valid_from": instant(authorization.valid_from),
        "valid_until": instant(authorization.valid_until),
        "service_ref": authorization.service_ref,
        "scope": {
            "level": authorization.scope.level.value,
            "value": authorization.scope.value,
        },
        "pins": {
            "policy_digest": authorization.pins.policy_digest,
            "target_revision": authorization.pins.target_revision,
            "action_type_versions": list(authorization.pins.action_type_versions),
            "evidence_revisions": list(authorization.pins.evidence_revisions),
        },
        "envelope": {
            "action_types": list(authorization.envelope.action_types),
            "max_blast_radius": authorization.envelope.max_blast_radius,
            "max_duration_seconds": authorization.envelope.max_duration_seconds,
            "reversible": authorization.envelope.reversible,
            "rollback_contract": authorization.envelope.rollback_contract,
            "stop_conditions": list(authorization.envelope.stop_conditions),
        },
        "incident_classes": list(authorization.incident_classes),
        "responders": {
            "primary": authorization.responders.primary,
            "backup": authorization.responders.backup,
            "confirmed_at": instant(authorization.responders.confirmed_at),
        },
        "evidence": {
            "history_reviewed": authorization.evidence.history_reviewed,
            "precedent_ref": authorization.evidence.precedent_ref,
            "scenario_evidence_ref": authorization.evidence.scenario_evidence_ref,
        },
    }


def _approval_claims(authorization: StandingAuthorization) -> list[dict[str, object]]:
    return [
        {
            "principal": approval.principal,
            "role": approval.role.value,
            "approved_at": instant(approval.approved_at),
        }
        for approval in authorization.approvals
    ]


def _evidence_claims(authorization: StandingAuthorization) -> dict[str, object]:
    return {
        "history_reviewed": authorization.evidence.history_reviewed,
        "precedent_ref": authorization.evidence.precedent_ref,
        "scenario_evidence_ref": authorization.evidence.scenario_evidence_ref,
        "evidence_revisions": list(authorization.pins.evidence_revisions),
    }


def _json_object(value: str, *, name: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AuthorizationLifecycleError(f"{name} MUST contain canonical JSON") from exc
    if not isinstance(loaded, dict) or canonical_json(loaded) != value:
        raise AuthorizationLifecycleError(f"{name} MUST contain a canonical JSON object")
    return loaded


__all__ = [
    "AuthorizationProofBindings",
    "AuthorizationRevision",
    "authorization_revision_id",
]
