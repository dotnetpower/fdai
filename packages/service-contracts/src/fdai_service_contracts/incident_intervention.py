"""Versioned no-effect contract for authorized Incident intervention requests."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from unicodedata import category

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.operator import OperatorRole

INCIDENT_INTERVENTION_REQUEST_TOPIC = "operator.incident-intervention.requests"
INCIDENT_INTERVENTION_CONSUMER_GROUP = "core-incident-intervention-v1"
_UUID_PATTERN = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"


class IncidentInterventionAction(StrEnum):
    """Closed intervention actions accepted across the Operator/Core boundary."""

    GUIDANCE = "operator_guidance"
    CLOSE_AS_DEVELOPMENT = "close_as_development"
    CREATE_DEVELOPMENT_EXCEPTION = "create_development_exception"
    REVOKE_DEVELOPMENT_EXCEPTION = "revoke_development_exception"


class IncidentExceptionDuration(StrEnum):
    """Server-owned duration choices for exact-target intake exceptions."""

    ONE_DAY = "one_day"
    ONE_WEEK = "one_week"
    ONE_MONTH = "one_month"
    UNTIL_REVOKED = "until_revoked"


class IncidentInterventionContract(BaseModel):
    """Reject unknown fields and control characters at every wire boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(
            category(character) in {"Cc", "Cf"} for character in value
        ):
            raise ValueError("incident intervention text MUST NOT contain control characters")
        return value


class IncidentInterventionProposalBody(IncidentInterventionContract):
    """Validate an authenticated browser request before durable acceptance."""

    action: IncidentInterventionAction
    incident_id: Annotated[str, Field(pattern=_UUID_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=256)]
    expected_state: Literal["open", "triaging", "mitigated", "resolved", "closed"]
    comment: Annotated[str, Field(min_length=1, max_length=500)]
    duration: IncidentExceptionDuration | None = None
    exception_id: Annotated[str, Field(pattern=_UUID_PATTERN)] | None = None

    @model_validator(mode="after")
    def _validate_action_fields(self) -> IncidentInterventionProposalBody:
        if self.comment != self.comment.strip():
            raise ValueError("incident intervention comment MUST be trimmed")
        if self.action is IncidentInterventionAction.CREATE_DEVELOPMENT_EXCEPTION:
            if self.duration is None or self.exception_id is not None:
                raise ValueError("create exception requires duration and no exception_id")
        elif self.action is IncidentInterventionAction.REVOKE_DEVELOPMENT_EXCEPTION:
            if self.exception_id is None or self.duration is not None:
                raise ValueError("revoke exception requires exception_id and no duration")
        elif self.duration is not None or self.exception_id is not None:
            raise ValueError("guidance and close requests accept no exception fields")
        return self

    def required_role(self) -> OperatorRole:
        """Return the minimum ordinary Operator role for this exact request."""
        if (
            self.action is IncidentInterventionAction.CREATE_DEVELOPMENT_EXCEPTION
            and self.duration is IncidentExceptionDuration.UNTIL_REVOKED
        ):
            return OperatorRole.OWNER
        if self.action in {
            IncidentInterventionAction.CREATE_DEVELOPMENT_EXCEPTION,
            IncidentInterventionAction.REVOKE_DEVELOPMENT_EXCEPTION,
        }:
            return OperatorRole.APPROVER
        return OperatorRole.CONTRIBUTOR


class IncidentInterventionRequest(IncidentInterventionContract):
    """Carry one server-grounded intervention without execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_roles: tuple[OperatorRole, ...]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=256)]
    incident_id: Annotated[str, Field(pattern=_UUID_PATTERN)]
    target_ref: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    expected_state: Literal["open", "triaging", "mitigated", "resolved", "closed"]
    action: IncidentInterventionAction
    comment: Annotated[str, Field(min_length=1, max_length=500)]
    duration: IncidentExceptionDuration | None = None
    exception_id: Annotated[str, Field(pattern=_UUID_PATTERN)] | None = None
    requested_at: datetime
    request_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    accountable_agent: Literal["Saga"] = "Saga"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_request(self) -> IncidentInterventionRequest:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("incident intervention requested_at MUST be timezone-aware")
        body = IncidentInterventionProposalBody(
            action=self.action,
            incident_id=self.incident_id,
            correlation_id=self.correlation_id,
            expected_state=self.expected_state,
            comment=self.comment,
            duration=self.duration,
            exception_id=self.exception_id,
        )
        role_rank = {
            OperatorRole.READER: 0,
            OperatorRole.CONTRIBUTOR: 1,
            OperatorRole.APPROVER: 2,
            OperatorRole.OWNER: 3,
            OperatorRole.BREAK_GLASS: -1,
        }
        highest = max((role_rank[role] for role in self.principal_roles), default=-1)
        if highest < role_rank[body.required_role()]:
            raise ValueError("incident intervention principal roles do not meet the request floor")
        if self.request_digest != incident_intervention_request_digest(self):
            raise ValueError("incident intervention request digest does not match its content")
        return self


def incident_intervention_request_digest(request: IncidentInterventionRequest) -> str:
    """Return the canonical digest excluding only the digest field."""
    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


def incident_target_ref(resource_id: str) -> str:
    """Return a bounded non-reversible identity for one exact logical target."""
    normalized = resource_id.strip()
    if not 1 <= len(normalized) <= 2048:
        raise ValueError("incident target resource_id must contain 1 to 2048 characters")
    return f"sha256:{hashlib.sha256(normalized.encode()).hexdigest()}"


def build_incident_intervention_request(
    *,
    request_id: str,
    principal_id: str,
    principal_roles: tuple[OperatorRole, ...],
    idempotency_key: str,
    target_ref: str,
    body: IncidentInterventionProposalBody,
    requested_at: datetime,
) -> IncidentInterventionRequest:
    """Build one immutable request after server-owned target resolution."""
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "principal_id": principal_id,
        "principal_roles": [role.value for role in principal_roles],
        "idempotency_key": idempotency_key,
        "correlation_id": body.correlation_id,
        "incident_id": body.incident_id,
        "target_ref": target_ref,
        "expected_state": body.expected_state,
        "action": body.action.value,
        "comment": body.comment,
        "duration": body.duration.value if body.duration else None,
        "exception_id": body.exception_id,
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "accountable_agent": "Saga",
        "execution_authority": False,
    }
    return IncidentInterventionRequest.model_validate(
        {**material, "request_digest": canonical_digest(material)}
    )


__all__ = [
    "INCIDENT_INTERVENTION_CONSUMER_GROUP",
    "INCIDENT_INTERVENTION_REQUEST_TOPIC",
    "IncidentExceptionDuration",
    "IncidentInterventionAction",
    "IncidentInterventionProposalBody",
    "IncidentInterventionRequest",
    "build_incident_intervention_request",
    "incident_intervention_request_digest",
    "incident_target_ref",
]
