"""Build the content-free authentication receipt the Operator retains instead of a token."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from fdai_service_contracts import OperatorPrincipal, OperatorRole
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)
from pydantic import ValidationError

_LOCAL_RECEIPT_LIFETIME = timedelta(hours=1)


def live_authentication_receipt(
    claims: Mapping[str, object],
    *,
    principal: OperatorPrincipal,
    group_ids: Mapping[OperatorRole, str],
) -> OperatorAuthenticationReceipt | None:
    """Return a receipt from verified claims, or nothing when a required claim is absent.

    Only claim identifiers are retained: the token, its signature, and display identities are
    never read into the receipt. A missing tenant, token-id, or time claim yields no receipt, so
    an independent verifier later treats the command as unauthenticated rather than guessing.
    """

    issuer = claims.get("iss")
    audience = _audience(claims.get("aud"))
    tenant = claims.get("tid")
    token_id = claims.get("uti", claims.get("jti"))
    issued_at = _epoch(claims.get("iat"))
    expires_at = _epoch(claims.get("exp"))
    if (
        not isinstance(issuer, str)
        or audience is None
        or not isinstance(tenant, str)
        or not isinstance(token_id, str)
        or issued_at is None
        or expires_at is None
    ):
        return None
    try:
        return OperatorAuthenticationReceipt.create(
            evidence_class=OperatorAuthenticationEvidenceClass.LIVE,
            issuer=issuer,
            audience=audience,
            tenant_digest=tenant_digest(tenant),
            subject_id=principal.subject_id,
            principal_kind=principal.principal_kind.value,
            groups=tuple(principal.groups),
            token_id_digest=token_id_digest(token_id),
            issued_at=issued_at,
            expires_at=expires_at,
            roles=tuple(role.value for role in principal.roles),
            role_mapping_revision=_mapping_revision(group_ids),
        )
    except (ValidationError, ValueError):
        return None


def local_authentication_receipt(
    principal: OperatorPrincipal,
    *,
    session_token: str,
    group_ids: Mapping[OperatorRole, str],
    now: datetime | None = None,
) -> OperatorAuthenticationReceipt:
    """Return a loopback-class receipt that no deployed verifier may ever accept."""

    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    session_id = hashlib.sha256(("fdai-local-session:" + session_token).encode()).hexdigest()
    return OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
        issuer=LOCAL_LOOPBACK_ISSUER,
        audience=LOCAL_LOOPBACK_ISSUER,
        tenant_digest=tenant_digest(LOCAL_LOOPBACK_ISSUER),
        subject_id=principal.subject_id,
        principal_kind=principal.principal_kind.value,
        groups=tuple(principal.groups),
        token_id_digest=token_id_digest(session_id),
        issued_at=issued_at,
        expires_at=issued_at + _LOCAL_RECEIPT_LIFETIME,
        roles=tuple(role.value for role in principal.roles),
        role_mapping_revision=_mapping_revision(group_ids),
    )


def channel_authentication_receipt(
    principal: OperatorPrincipal,
    *,
    issuer: str,
    audience: str,
    tenant_ref: str,
    verification_ref: str,
    issued_at: datetime,
) -> OperatorAuthenticationReceipt:
    """Return a token-free receipt for a signed channel-edge request."""

    return OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LIVE,
        issuer=issuer,
        audience=audience,
        tenant_digest=tenant_digest(tenant_ref),
        subject_id=principal.subject_id,
        principal_kind=principal.principal_kind.value,
        groups=tuple(principal.groups),
        token_id_digest=token_id_digest(verification_ref),
        issued_at=issued_at,
        expires_at=issued_at + _LOCAL_RECEIPT_LIFETIME,
        roles=tuple(role.value for role in principal.roles),
        role_mapping_revision=role_mapping_revision({}),
    )


def _mapping_revision(group_ids: Mapping[OperatorRole, str]) -> str:
    return role_mapping_revision({role.value: group for role, group in group_ids.items()})


def _audience(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (list, tuple)) and len(value) == 1 and isinstance(value[0], str):
        return value[0].strip() or None
    return None


def _epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


__all__ = [
    "channel_authentication_receipt",
    "live_authentication_receipt",
    "local_authentication_receipt",
]
