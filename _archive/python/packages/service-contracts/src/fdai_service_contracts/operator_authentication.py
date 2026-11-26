"""Content-free Operator authentication receipt retained instead of any bearer token.

The Operator service builds this receipt when it verifies a human or workload token. It keeps
the facts an independent verifier needs to re-establish the authenticated principal - issuer,
audience, tenant digest, subject, principal kind, exact groups, token-id digest, validity, roles,
and the role-mapping revision - and never the token, its signature, or a display identity.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.ontology_query import content_digest

_MAX_LIFETIME = timedelta(hours=24)
_ROLES = frozenset({"Reader", "Contributor", "Approver", "Owner", "BreakGlass"})
_BOUNDED_TEXT = re.compile(r"^[^\x00-\x1f]{1,512}$")
LOCAL_LOOPBACK_ISSUER = "local-loopback"


class OperatorAuthenticationEvidenceClass(StrEnum):
    """Whether the receipt came from a verified live token or the loopback CLI session."""

    LIVE = "live"
    LOCAL_LOOPBACK = "local-loopback"


class _ReceiptBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    evidence_class: OperatorAuthenticationEvidenceClass
    issuer: Annotated[str, Field(min_length=1, max_length=512)]
    audience: Annotated[str, Field(min_length=1, max_length=512)]
    tenant_digest: Digest
    subject_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_kind: Literal["human", "workload"]
    groups: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    group_overage: Literal[False] = False
    token_id_digest: Digest
    issued_at: datetime
    expires_at: datetime
    roles: Annotated[tuple[str, ...], Field(max_length=8)] = ()
    role_mapping_revision: Digest
    token_retained: Literal[False] = False

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authentication receipt time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _exact_identity(self) -> _ReceiptBody:
        for value in (self.issuer, self.audience, self.subject_id, *self.groups):
            if _BOUNDED_TEXT.fullmatch(value) is None:
                raise ValueError("authentication receipt identifiers MUST be bounded text")
        if self.groups != tuple(sorted(set(self.groups))):
            raise ValueError("authentication receipt groups MUST be unique and ordered")
        if self.roles != tuple(sorted(set(self.roles))) or set(self.roles) - _ROLES:
            raise ValueError("authentication receipt roles MUST be unique canonical roles")
        if not self.issued_at < self.expires_at <= self.issued_at + _MAX_LIFETIME:
            raise ValueError("authentication receipt validity MUST be positive and bounded")
        if self.principal_kind == "workload" and self.groups:
            raise ValueError("workload authentication receipts MUST NOT carry groups")
        local = self.evidence_class is OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
        if local != (self.issuer == LOCAL_LOOPBACK_ISSUER):
            raise ValueError("only local-loopback receipts may use the loopback issuer")
        return self


class OperatorAuthenticationReceipt(_ReceiptBody):
    """Immutable, token-free authentication facts; possession grants no authority."""

    receipt_digest: Digest

    @model_validator(mode="after")
    def _digest_matches(self) -> OperatorAuthenticationReceipt:
        expected = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("authentication receipt digest mismatched")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        """Canonicalize ordered groups and roles, then content-address the receipt."""

        body = dict(values)
        body.pop("receipt_digest", None)
        for name in ("groups", "roles"):
            raw = body.get(name, ())
            if isinstance(raw, (list, tuple, set, frozenset)):
                body[name] = tuple(sorted({str(item) for item in raw}))
        candidate = _ReceiptBody.model_validate(body)
        payload = candidate.model_dump(mode="json")
        return cls.model_validate({**payload, "receipt_digest": content_digest(payload)})

    def valid_at(self, evaluated_at: datetime) -> bool:
        """Return whether the verified token was current at one exact instant."""

        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("authentication receipt evaluation time MUST include a timezone")
        return self.issued_at <= evaluated_at.astimezone(UTC) < self.expires_at


def tenant_digest(tenant_id: str) -> str:
    """Return the opaque tenant digest retained in place of the tenant identifier."""

    return content_digest({"tenant": tenant_id.strip().casefold()})


def token_id_digest(token_id: str) -> str:
    """Return a domain-separated digest of a token identifier claim, never of the token."""

    return content_digest({"token_id": token_id.strip()})


def role_mapping_revision(group_ids: dict[str, str]) -> str:
    """Return the revision of the server-owned role-to-group mapping used for resolution."""

    return content_digest({"role_groups": dict(sorted(group_ids.items()))})


__all__ = [
    "LOCAL_LOOPBACK_ISSUER",
    "OperatorAuthenticationEvidenceClass",
    "OperatorAuthenticationReceipt",
    "role_mapping_revision",
    "tenant_digest",
    "token_id_digest",
]
