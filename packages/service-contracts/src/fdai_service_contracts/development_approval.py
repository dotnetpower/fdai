"""Operator attestation that one Owner freshly authenticated to approve one exact parked action.

The Operator derives every field from verified Entra token claims and the Core-written park
block. The attestation carries no token and grants nothing by itself: Core admits a development
self-approval only after revalidating it against durable state and its selected profile.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEVELOPMENT_PARK_BLOCK_FIELD = "development_authority"
DEVELOPMENT_APPROVAL_ATTESTATION_FIELD = "development_attestation"
MAX_DEVELOPMENT_AUTHENTICATION_AGE = timedelta(minutes=10)
MAX_DEVELOPMENT_CLOCK_SKEW = timedelta(seconds=60)

_Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class DevelopmentApprovalAttestation(BaseModel):
    """Fresh-authentication facts for one development self-approval of one parked action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    confirmation_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
    approval_id: Annotated[str, Field(min_length=1, max_length=200)]
    block_digest: _Digest
    binding_digest: _Digest
    profile_digest: _Digest
    authenticated_principal: Annotated[str, Field(min_length=1, max_length=256)]
    authenticated_role: Literal["Owner"] = "Owner"
    authenticated_at: datetime
    authentication_evidence_digest: _Digest
    confirmed_at: datetime

    @model_validator(mode="after")
    def _times_are_ordered(self) -> Self:
        for value in (self.authenticated_at, self.confirmed_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("development attestation times MUST be timezone-aware")
        if self.confirmed_at < self.authenticated_at:
            raise ValueError("development confirmation MUST NOT precede authentication")
        return self


def development_authentication_evidence_digest(
    *,
    principal: str,
    auth_time: int,
    token_id: str,
    approval_id: str,
) -> str:
    """Digest the signed claims that prove one fresh sign-in, without retaining the token id."""
    if not principal.strip() or not token_id.strip() or not approval_id.strip():
        raise ValueError("development authentication evidence MUST be complete")
    material = "\0".join((principal.strip().casefold(), str(auth_time), token_id, approval_id))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def fresh_development_authentication(
    *,
    auth_time: datetime,
    parked_at: datetime,
    now: datetime,
) -> bool:
    """Return whether a sign-in happened after the park and is still inside the approval age.

    Entra records whole seconds, so only a later second proves a sign-in after the park.
    """
    return (
        int(auth_time.timestamp()) > int(parked_at.timestamp())
        and auth_time <= now + MAX_DEVELOPMENT_CLOCK_SKEW
        and now - auth_time <= MAX_DEVELOPMENT_AUTHENTICATION_AGE
    )


__all__ = [
    "DEVELOPMENT_APPROVAL_ATTESTATION_FIELD",
    "DEVELOPMENT_PARK_BLOCK_FIELD",
    "MAX_DEVELOPMENT_AUTHENTICATION_AGE",
    "MAX_DEVELOPMENT_CLOCK_SKEW",
    "DevelopmentApprovalAttestation",
    "development_authentication_evidence_digest",
    "fresh_development_authentication",
]
