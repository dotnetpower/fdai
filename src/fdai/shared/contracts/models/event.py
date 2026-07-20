"""Event contract - the normalised message that enters the control loop."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

from ._base import IdempotencyKey, SemVer, _Base
from .enums import Decision, IncidentCorrelation, Mode, Tier


class Event(_Base):
    """Normalized event entering the control loop.

    Payloads (``payload`` field) are untrusted; the verifier and policy re-check
    are the authority, never model or event text.
    """

    schema_version: SemVer
    event_id: UUID
    idempotency_key: IdempotencyKey
    correlation_id: str | None = None
    source: Annotated[str, Field(min_length=1)]
    event_type: Annotated[str, Field(min_length=1)]
    resource_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime
    ingested_at: datetime
    incident_correlation: IncidentCorrelation = IncidentCorrelation.CORRELATE
    tier: Tier | None = None
    decision: Decision | None = None
    mode: Mode


__all__ = ["Event"]
