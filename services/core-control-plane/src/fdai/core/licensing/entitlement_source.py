"""Local acceptance of existing full grants without adding an issuer or Trial path."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fdai.core.licensing.entitlement import LicenseEntitlementAuthority, LicenseStatus
from fdai.core.licensing.installation_entitlement import (
    INSTALLATION_ENTITLEMENT_SCHEMA,
    InstallationEntitlementClaims,
    parse_installation_entitlement,
    signed_document_schema,
)
from fdai.core.licensing.token import LicenseTokenError


class EntitlementAcceptanceConflictError(RuntimeError):
    """A different original grant is already authoritative for the installation."""


@dataclass(frozen=True, slots=True)
class EntitlementAcceptance:
    acceptance_id: str
    token_digest: str
    accepted_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "fdai.installation-entitlement-acceptance.v1",
            "acceptance_id": self.acceptance_id,
            "token_digest": self.token_digest,
            "accepted_at": self.accepted_at.astimezone(UTC).isoformat(),
            "execution_authority": False,
        }


def admitted_installation_entitlement(
    token: str, *, authority: LicenseEntitlementAuthority, now: datetime
) -> InstallationEntitlementClaims:
    """Use the existing authority with local-issuer and Trial bypasses disabled."""
    if now.utcoffset() is None:
        raise ValueError("entitlement acceptance requires an aware timestamp")
    if signed_document_schema(token) != INSTALLATION_ENTITLEMENT_SCHEMA:
        raise LicenseTokenError("local acceptance requires an existing installation full grant")
    candidate = replace(
        authority,
        token=token,
        token_source=None,
        issuer_workstation=False,
        trial=None,
        require_license=True,
    )
    entitlement = candidate.resolve(now=now)
    if entitlement.status is not LicenseStatus.ACTIVE:
        raise LicenseTokenError(
            f"installation entitlement acceptance denied: {entitlement.status.value}"
        )
    claims, _document, _signature = parse_installation_entitlement(token)
    return claims


def entitlement_token_digest(token: str) -> str:
    if not isinstance(token, str) or not 1 <= len(token) <= 8192:
        raise LicenseTokenError("installation entitlement token is empty or exceeds its bound")
    try:
        encoded = token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise LicenseTokenError("installation entitlement token must be ASCII") from exc
    return hashlib.sha256(encoded).hexdigest()


def acceptance_identity(
    installation_binding: str, deployment_binding: str, token_digest: str
) -> str:
    return hashlib.sha256(
        (
            "fdai.installation-entitlement-acceptance.v1\x00"
            + installation_binding
            + "\x00"
            + deployment_binding
            + "\x00"
            + token_digest
        ).encode("ascii")
    ).hexdigest()
