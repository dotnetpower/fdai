"""Versioned no-effect contracts for confirmed operator Incident creation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Final, Literal
from unicodedata import category

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.operator import OperatorPrincipalKind, OperatorRole

INCIDENT_CREATION_REQUEST_TOPIC = "operator.incident-creation.requests"
INCIDENT_CREATION_CONSUMER_GROUP = "core-incident-creation-v1"
INCIDENT_CREATE_ACTION_TYPE: Final[Literal["incident.create"]] = "incident.create"
INCIDENT_CREATION_DRAFT_TTL = timedelta(minutes=10)
IncidentCreationSeverity = Literal["sev1", "sev2", "sev3", "sev4", "sev5"]

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_UUID_PATTERN = r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
_ROLE_RANK = {
    OperatorRole.READER: 0,
    OperatorRole.CONTRIBUTOR: 1,
    OperatorRole.APPROVER: 2,
    OperatorRole.OWNER: 3,
    OperatorRole.BREAK_GLASS: -1,
}


class IncidentCreationContract(BaseModel):
    """Reject unknown fields and control characters at every wire boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(
            category(character) in {"Cc", "Cf"} for character in value
        ):
            raise ValueError("incident creation text MUST NOT contain control characters")
        return value


class IncidentCreationArguments(IncidentCreationContract):
    """Canonical incident fields selected by semantic judgment."""

    severity: IncidentCreationSeverity
    target: Annotated[str, Field(min_length=1, max_length=256)]

    @field_validator("target")
    @classmethod
    def _target_is_trimmed(cls, value: str) -> str:
        if value != value.strip() or "|" in value:
            raise ValueError(
                "incident creation target MUST be trimmed and contain no reserved delimiter"
            )
        return value


class IncidentCreationIntent(IncidentCreationContract):
    """Authority-free incident candidate retained by semantic planning."""

    action_type: Literal["incident.create"] = INCIDENT_CREATE_ACTION_TYPE
    arguments: IncidentCreationArguments
    source_input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False


class IncidentCreationDraft(IncidentCreationContract):
    """Bounded confirmation draft projected to one authenticated browser session."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    action_type: Literal["incident.create"] = INCIDENT_CREATE_ACTION_TYPE
    arguments: IncidentCreationArguments
    session_id: Annotated[str, Field(min_length=1, max_length=200)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    source_input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    prepared_at: datetime
    expires_at: datetime
    draft_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _identity_is_exact_and_bounded(self) -> IncidentCreationDraft:
        if (
            self.prepared_at.tzinfo is None
            or self.prepared_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or not self.prepared_at < self.expires_at
            or self.expires_at - self.prepared_at > INCIDENT_CREATION_DRAFT_TTL
        ):
            raise ValueError("incident creation draft expiry is invalid")
        if self.draft_digest != incident_creation_draft_digest(self):
            raise ValueError("incident creation draft digest does not match its content")
        return self


class IncidentCreationConfirmationBody(IncidentCreationContract):
    """Minimal browser confirmation for one server-owned incident draft."""

    action_type: Literal["incident.create"] = INCIDENT_CREATE_ACTION_TYPE
    arguments: IncidentCreationArguments
    session_id: Annotated[str, Field(min_length=1, max_length=200)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]


class IncidentCreationRequest(IncidentCreationContract):
    """Authenticated, replay-safe request consumed by Core Incident authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_request_id: Annotated[str, Field(pattern=_UUID_PATTERN)]
    source_projection_id: Annotated[str, Field(pattern=_UUID_PATTERN)]
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_roles: tuple[OperatorRole, ...]
    principal_kind: Literal[OperatorPrincipalKind.HUMAN] = OperatorPrincipalKind.HUMAN
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    session_id: Annotated[str, Field(min_length=1, max_length=200)]
    action_type: Literal["incident.create"] = INCIDENT_CREATE_ACTION_TYPE
    arguments: IncidentCreationArguments
    source_input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    draft_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    draft_expires_at: datetime
    target_ref: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    confirmed_at: datetime
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    accountable_agent: Literal["Saga"] = "Saga"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _request_is_authorized_and_exact(self) -> IncidentCreationRequest:
        if (
            self.confirmed_at.tzinfo is None
            or self.confirmed_at.utcoffset() is None
            or self.draft_expires_at.tzinfo is None
            or self.draft_expires_at.utcoffset() is None
            or self.confirmed_at > self.draft_expires_at
        ):
            raise ValueError("incident creation confirmation time is invalid")
        if len(self.principal_roles) != len(set(self.principal_roles)):
            raise ValueError("incident creation principal_roles MUST be unique")
        if OperatorRole.BREAK_GLASS in self.principal_roles or self.principal_roles != tuple(
            sorted(self.principal_roles, key=lambda role: _ROLE_RANK[role])
        ):
            raise ValueError("incident creation principal_roles MUST be ordered ordinary roles")
        highest = max((_ROLE_RANK[role] for role in self.principal_roles), default=-1)
        if highest < _ROLE_RANK[OperatorRole.CONTRIBUTOR]:
            raise ValueError("incident creation requires a Contributor-or-higher principal")
        if self.target_ref != incident_creation_target_ref(self.arguments.target):
            raise ValueError("incident creation target_ref does not match its target")
        if self.request_digest != incident_creation_request_digest(self):
            raise ValueError("incident creation request digest does not match its content")
        return self


def incident_creation_draft_digest(draft: IncidentCreationDraft) -> str:
    """Return the canonical digest excluding only the draft digest field."""

    return canonical_digest(draft.model_dump(mode="json", exclude={"draft_digest"}))


def build_incident_creation_draft(
    *,
    intent: IncidentCreationIntent,
    session_id: str,
    idempotency_key: str,
    prepared_at: datetime,
) -> IncidentCreationDraft:
    """Bind a semantic incident intent to one expiring confirmation draft."""

    prototype = IncidentCreationDraft.model_construct(
        schema_version="1.0.0",
        action_type=INCIDENT_CREATE_ACTION_TYPE,
        arguments=intent.arguments,
        session_id=session_id,
        idempotency_key=idempotency_key,
        source_input_digest=intent.source_input_digest,
        prepared_at=prepared_at,
        expires_at=prepared_at + INCIDENT_CREATION_DRAFT_TTL,
        draft_digest="sha256:" + "0" * 64,
        authority="candidate_only",
        execution_authority=False,
    )
    return IncidentCreationDraft(
        action_type=INCIDENT_CREATE_ACTION_TYPE,
        arguments=intent.arguments,
        session_id=session_id,
        idempotency_key=idempotency_key,
        source_input_digest=intent.source_input_digest,
        prepared_at=prepared_at,
        expires_at=prepared_at + INCIDENT_CREATION_DRAFT_TTL,
        draft_digest=incident_creation_draft_digest(prototype),
    )


def incident_creation_target_ref(target: str) -> str:
    """Return a bounded non-reversible partition identity for one target."""

    normalized = target.strip()
    if (
        normalized != target
        or not 1 <= len(normalized) <= 256
        or "|" in normalized
        or any(category(character) in {"Cc", "Cf"} for character in normalized)
    ):
        raise ValueError("incident creation target MUST be a trimmed bounded string")
    return f"sha256:{hashlib.sha256(normalized.encode()).hexdigest()}"


def incident_creation_request_digest(request: IncidentCreationRequest) -> str:
    """Return the canonical digest excluding only the request digest field."""

    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


def build_incident_creation_request(
    *,
    request_id: str,
    source_request_id: str,
    source_projection_id: str,
    principal_id: str,
    principal_roles: tuple[OperatorRole, ...],
    idempotency_key: str,
    session_id: str,
    arguments: IncidentCreationArguments,
    source_input_digest: str,
    draft_digest: str,
    draft_expires_at: datetime,
    confirmed_at: datetime,
) -> IncidentCreationRequest:
    """Build one immutable request from a revalidated server-side draft."""

    ordered_roles = tuple(sorted(principal_roles, key=lambda role: _ROLE_RANK[role]))
    target_ref = incident_creation_target_ref(arguments.target)
    prototype = IncidentCreationRequest.model_construct(
        schema_version="1.0.0",
        request_id=request_id,
        source_request_id=source_request_id,
        source_projection_id=source_projection_id,
        principal_id=principal_id,
        principal_roles=ordered_roles,
        principal_kind=OperatorPrincipalKind.HUMAN,
        idempotency_key=idempotency_key,
        session_id=session_id,
        action_type=INCIDENT_CREATE_ACTION_TYPE,
        arguments=arguments,
        source_input_digest=source_input_digest,
        draft_digest=draft_digest,
        draft_expires_at=draft_expires_at,
        target_ref=target_ref,
        confirmed_at=confirmed_at,
        request_digest="sha256:" + "0" * 64,
        accountable_agent="Saga",
        execution_authority=False,
    )
    return IncidentCreationRequest(
        request_id=request_id,
        source_request_id=source_request_id,
        source_projection_id=source_projection_id,
        principal_id=principal_id,
        principal_roles=ordered_roles,
        idempotency_key=idempotency_key,
        session_id=session_id,
        arguments=arguments,
        source_input_digest=source_input_digest,
        draft_digest=draft_digest,
        draft_expires_at=draft_expires_at,
        target_ref=target_ref,
        confirmed_at=confirmed_at,
        request_digest=incident_creation_request_digest(prototype),
    )


__all__ = [
    "INCIDENT_CREATE_ACTION_TYPE",
    "INCIDENT_CREATION_CONSUMER_GROUP",
    "INCIDENT_CREATION_DRAFT_TTL",
    "INCIDENT_CREATION_REQUEST_TOPIC",
    "IncidentCreationArguments",
    "IncidentCreationConfirmationBody",
    "IncidentCreationDraft",
    "IncidentCreationIntent",
    "IncidentCreationRequest",
    "IncidentCreationSeverity",
    "build_incident_creation_draft",
    "build_incident_creation_request",
    "incident_creation_draft_digest",
    "incident_creation_request_digest",
    "incident_creation_target_ref",
]
