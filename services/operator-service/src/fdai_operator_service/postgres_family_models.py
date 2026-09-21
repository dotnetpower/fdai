"""Exceptions and immutable records for the Operator PostgreSQL family store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


class PostgresFamilyStoreUnavailableError(RuntimeError):
    """The authoritative PostgreSQL family store could not satisfy a request."""


class PostgresProposalConflictError(RuntimeError):
    """An idempotency key is already bound to different proposal content."""


class PostgresProcessNotVisibleError(RuntimeError):
    """A Process is absent from the authenticated principal's visible scope."""


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """Durable inert proposal acceptance loaded from the service outbox namespace."""

    proposal_id: str
    accepted_at: str
    duplicate: bool
    record: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ActionProposalClaim:
    """One lease-fenced generic Operator proposal awaiting Core publication."""

    key: str
    claim_id: str
    principal_id: str
    payload: Mapping[str, object]
    accepted_at: str
    attempt: int


@dataclass(frozen=True, slots=True)
class WebhookProposalClaim:
    """One lease-fenced normalized webhook proposal awaiting publication."""

    key: str
    claim_id: str
    payload: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class HilDecisionProposalClaim:
    """One lease-fenced durable human-approval decision awaiting publication."""

    key: str
    claim_id: str
    payload: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class ReportLineContactProposalClaim:
    """One lease-fenced requester contact command awaiting publication."""

    key: str
    claim_id: str
    payload: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class ReadInvestigationProposalClaim:
    """One lease-fenced read proposal awaiting versioned Core publication."""

    key: str
    claim_id: str
    request_id: str
    principal_id: str
    idempotency_key: str
    correlation_id: str | None
    payload: Mapping[str, object]
    accepted_at: str
    attempt: int


@dataclass(frozen=True, slots=True)
class IncidentInterventionProposalClaim:
    """One lease-fenced Incident intervention awaiting versioned publication."""

    key: str
    claim_id: str
    request_id: str
    principal_id: str
    idempotency_key: str
    correlation_id: str
    payload: Mapping[str, object]
    accepted_at: str
    attempt: int


@dataclass(frozen=True, slots=True)
class StoredReplayEvent:
    """One monotonic audit event selected for an Operator replay stream."""

    sequence: int
    event: str
    data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StoredStateRecord:
    """One authoritative state record with the write time that orders its replay."""

    key: str
    value: Mapping[str, object]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredStatePage:
    """One bounded page of state records plus whether the scan proved complete coverage."""

    records: tuple[StoredStateRecord, ...]
    truncated: bool
