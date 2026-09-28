"""Owner development self-approval at the Operator HIL decision boundary.

Core writes the ``development_authority`` block when it parks an Owner's own request under the
selected full-authority development profile. The Operator admits that Owner's self-approval only
from the Console, only for an approve decision, and only after a signed ``auth_time`` claim proves
a sign-in after the park. The resulting attestation is evidence, not authority: the decision
transaction and Core each revalidate it before anything executes.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from fdai_service_contracts import OperatorRole
from fdai_service_contracts.development_approval import (
    DEVELOPMENT_PARK_BLOCK_FIELD,
    DevelopmentApprovalAttestation,
    development_authentication_evidence_digest,
    fresh_development_authentication,
)
from pydantic import ValidationError

_METADATA_FIELDS = {
    "development_owner_principal": "owner_principal",
    "development_block_digest": "block_digest",
    "development_binding_digest": "binding_digest",
    "development_profile_digest": "profile_digest",
    "development_expires_at": "expires_at",
}


def development_metadata(state: Mapping[str, object]) -> dict[str, str]:
    """Flatten a complete Core-written park block into callback metadata strings."""
    block = state.get(DEVELOPMENT_PARK_BLOCK_FIELD)
    parked_at = state.get("parked_at")
    if not isinstance(block, Mapping) or not isinstance(parked_at, str) or not parked_at:
        return {}
    fields = {name: block.get(source) for name, source in _METADATA_FIELDS.items()}
    if not all(isinstance(value, str) and value for value in fields.values()):
        return {}
    return {**{name: str(value) for name, value in fields.items()}, "parked_at": parked_at}


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def development_attestation(
    *,
    claims: Mapping[str, object],
    actor_oid: str,
    actor_roles: frozenset[OperatorRole],
    approval_id: str,
    metadata: Mapping[str, str],
    now: datetime,
) -> DevelopmentApprovalAttestation | None:
    """Return the fresh-authentication attestation for an eligible Owner, or ``None``."""
    owner = metadata.get("development_owner_principal", "").strip().casefold()
    expires_at = _instant(metadata.get("development_expires_at"))
    parked_at = _instant(metadata.get("parked_at"))
    auth_time = claims.get("auth_time")
    token_id = claims.get("uti", claims.get("jti"))
    if (
        not owner
        or owner != actor_oid.strip().casefold()
        or str(claims.get("oid", "")).strip().casefold() != owner
        or OperatorRole.OWNER not in actor_roles
        or expires_at is None
        or expires_at <= now
        or parked_at is None
        or type(auth_time) is not int
        or not isinstance(token_id, str)
        or not token_id
    ):
        return None
    signed_at = datetime.fromtimestamp(auth_time, UTC)
    if not fresh_development_authentication(auth_time=signed_at, parked_at=parked_at, now=now):
        return None
    evidence = development_authentication_evidence_digest(
        principal=owner,
        auth_time=auth_time,
        token_id=token_id,
        approval_id=approval_id,
    )
    try:
        return DevelopmentApprovalAttestation(
            confirmation_id="development-confirmation:" + evidence.removeprefix("sha256:")[:40],
            approval_id=approval_id,
            block_digest=metadata["development_block_digest"],
            binding_digest=metadata["development_binding_digest"],
            profile_digest=metadata["development_profile_digest"],
            authenticated_principal=owner,
            authenticated_at=signed_at,
            authentication_evidence_digest=evidence,
            confirmed_at=max(now, signed_at),
        )
    except (KeyError, ValueError, ValidationError):
        return None


def development_self_approval_admitted(
    parked: Mapping[str, object],
    *,
    approver_oid: str,
    approver_roles: frozenset[OperatorRole],
    decision: str,
    attestation: Mapping[str, object] | None,
    now: datetime,
) -> bool:
    """Revalidate an Owner self-approval against the exact locked park row."""
    if attestation is None or decision != "approve" or OperatorRole.OWNER not in approver_roles:
        return False
    try:
        attested = DevelopmentApprovalAttestation.model_validate(dict(attestation))
    except (TypeError, ValueError, ValidationError):
        return False
    metadata = development_metadata(parked)
    parked_at = _instant(metadata.get("parked_at"))
    expires_at = _instant(metadata.get("development_expires_at"))
    approver = approver_oid.strip().casefold()
    return (
        bool(metadata)
        and parked_at is not None
        and expires_at is not None
        and now < expires_at
        and metadata["development_owner_principal"].strip().casefold() == approver
        and attested.authenticated_principal.strip().casefold() == approver
        and attested.approval_id == parked.get("approval_id")
        and attested.block_digest == metadata["development_block_digest"]
        and attested.binding_digest == metadata["development_binding_digest"]
        and attested.profile_digest == metadata["development_profile_digest"]
        and fresh_development_authentication(
            auth_time=attested.authenticated_at,
            parked_at=parked_at,
            now=now,
        )
    )


__all__ = [
    "development_attestation",
    "development_metadata",
    "development_self_approval_admitted",
]
