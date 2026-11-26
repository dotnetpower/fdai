"""Durable JSON codec for governance promotion attestations and replay receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
)

from fdai.core.rbac.roles import Role
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
)
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiReceipt,
)


@dataclass(frozen=True, slots=True)
class GovernancePromotionAttestation:
    """Authenticated review result bound to one exact promotion request."""

    review: GovernanceReviewRequest
    action_type_id: str
    fdai_revision: str
    scenario_set_version: str
    evidence_digest: str
    idempotency_key: str
    nonce: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.action_type_id,
                self.fdai_revision,
                self.scenario_set_version,
                self.evidence_digest,
                self.idempotency_key,
                self.nonce,
                self.request_fingerprint,
            )
        ):
            raise ValueError("promotion attestation identity MUST be non-empty")

    def as_json(self) -> dict[str, object]:
        """Serialize the validated review attestation for durable one-time use."""
        return {
            "action_type_id": self.action_type_id,
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "evidence_digest": self.evidence_digest,
            "idempotency_key": self.idempotency_key,
            "nonce": self.nonce,
            "request_fingerprint": self.request_fingerprint,
            "review": {
                "change_class": self.review.change_class.value,
                "author": {
                    "oid": self.review.author.oid,
                    "roles": sorted(role.value for role in self.review.author.roles),
                },
                "head_revision": self.review.head_revision,
                "head_committed_at": self.review.head_committed_at.isoformat(),
                "approvals": [
                    {
                        "approver": {
                            "oid": approval.approver.oid,
                            "roles": sorted(role.value for role in approval.approver.roles),
                        },
                        "reviewed_revision": approval.reviewed_revision,
                        "approved_at": approval.approved_at.isoformat(),
                        "phishing_resistant": approval.phishing_resistant,
                        "dismissed": approval.dismissed,
                    }
                    for approval in self.review.approvals
                ],
                "co_author_oids": sorted(self.review.co_author_oids),
                "committer_oids": sorted(self.review.committer_oids),
                "approval_profile": (
                    self.review.approval_profile.as_audit_dict()
                    if self.review.approval_profile is not None
                    else None
                ),
            },
        }


def attestation_from_json(raw: Mapping[str, Any]) -> GovernancePromotionAttestation:
    review_raw = _mapping(raw.get("review"), "review")
    author_raw = _mapping(review_raw.get("author"), "author")
    approvals: list[GovernanceApproval] = []
    raw_approvals = review_raw.get("approvals")
    if not isinstance(raw_approvals, list):
        raise DirectApiPreconditionError("promotion attestation approvals are malformed")
    for item in raw_approvals:
        approval_raw = _mapping(item, "approval")
        principal_raw = _mapping(approval_raw.get("approver"), "approver")
        approvals.append(
            GovernanceApproval(
                approver=GovernancePrincipal(
                    oid=_text(principal_raw, "oid"),
                    roles=_roles(principal_raw.get("roles")),
                ),
                reviewed_revision=_text(approval_raw, "reviewed_revision"),
                approved_at=_timestamp(approval_raw, "approved_at"),
                phishing_resistant=_bool(approval_raw, "phishing_resistant"),
                dismissed=_bool(approval_raw, "dismissed"),
            )
        )
    return GovernancePromotionAttestation(
        review=GovernanceReviewRequest(
            change_class=GovernanceChangeClass(_text(review_raw, "change_class")),
            author=GovernancePrincipal(
                oid=_text(author_raw, "oid"),
                roles=_roles(author_raw.get("roles")),
            ),
            head_revision=_text(review_raw, "head_revision"),
            head_committed_at=_timestamp(review_raw, "head_committed_at"),
            approvals=tuple(approvals),
            co_author_oids=frozenset(_strings(review_raw.get("co_author_oids"))),
            committer_oids=frozenset(_strings(review_raw.get("committer_oids"))),
            approval_profile=_approval_profile(review_raw.get("approval_profile")),
        ),
        action_type_id=_text(raw, "action_type_id"),
        fdai_revision=_text(raw, "fdai_revision"),
        scenario_set_version=_text(raw, "scenario_set_version"),
        evidence_digest=_text(raw, "evidence_digest"),
        idempotency_key=_text(raw, "idempotency_key"),
        nonce=_text(raw, "nonce"),
        request_fingerprint=_text(raw, "request_fingerprint"),
    )


def direct_api_receipt_json(receipt: DirectApiReceipt) -> dict[str, object]:
    return {
        "outcome": receipt.outcome.value,
        "receipt_ref": receipt.receipt_ref,
        "already_existed": receipt.already_existed,
        "rollback_succeeded": receipt.rollback_succeeded,
        "detail": receipt.detail,
    }


def direct_api_receipt_from_json(raw: Mapping[str, Any]) -> DirectApiReceipt:
    receipt_ref = raw.get("receipt_ref")
    if not isinstance(receipt_ref, str) or not receipt_ref:
        raise DirectApiPreconditionError("promotion replay receipt is malformed")
    return DirectApiReceipt(
        outcome=DirectApiOutcome(_text(raw, "outcome")),
        receipt_ref=receipt_ref,
        already_existed=_bool(raw, "already_existed"),
        rollback_succeeded=(
            _bool(raw, "rollback_succeeded") if raw.get("rollback_succeeded") is not None else None
        ),
        detail=_text(raw, "detail") if raw.get("detail") is not None else None,
    )


def promotion_attestation_digest(attestation: GovernancePromotionAttestation) -> str:
    """Return the stable digest of the exact Var approval attestation."""

    return hashlib.sha256(
        json.dumps(
            attestation.as_json(),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed")
    return value


def _text(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed")
    return value


def _bool(raw: Mapping[str, Any], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed")
    return value


def _timestamp(raw: Mapping[str, Any], name: str) -> datetime:
    value = _text(raw, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DirectApiPreconditionError(f"promotion attestation {name} is not timezone-aware")
    return parsed


def _approval_profile(value: object) -> ApprovalProfileRevision | None:
    if value is None:
        return None
    raw = _mapping(value, "approval_profile")
    operator = raw.get("operator_principal")
    return ApprovalProfileRevision(
        revision_id=_text(raw, "revision_id"),
        approval_profile=ApprovalProfileKind(_text(raw, "approval_profile")),
        executor_principal=_text(raw, "executor_principal"),
        policy_digest=_text(raw, "policy_digest"),
        effective_from=_timestamp(raw, "effective_from"),
        operator_principal=(str(operator) if operator is not None else None),
    )


def optional_timestamp(value: object) -> datetime | None:
    """Parse a stored lease deadline, treating anything malformed as absent.

    An absent or unparsable ``reserved_until`` MUST NOT be treated as an
    expired lease - :meth:`fdai.delivery.promotion.StateStorePromotionAttestationStore.consume`
    only reclaims a ``reserved`` record once its deadline has genuinely
    passed, so a missing/corrupt field fails closed (not reclaimable)
    rather than accidentally granting an early reclaim.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _roles(value: object) -> frozenset[Role]:
    return frozenset(Role(item) for item in _strings(value))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DirectApiPreconditionError("promotion attestation string list is malformed")
    return tuple(value)


__all__ = [
    "GovernancePromotionAttestation",
    "attestation_from_json",
    "direct_api_receipt_from_json",
    "direct_api_receipt_json",
    "optional_timestamp",
]
