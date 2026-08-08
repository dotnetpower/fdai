"""Incident contract - the first-class correlation entity.

See ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.1``. Groups many Events /
Findings / Actions under one lifecycle so postmortems, on-call handoffs,
and after-action reviews have a durable anchor. The state machine is
enforced by ``core/incident``; this model is the wire shape only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from ._base import SemVer, _Base
from .enums import IncidentSeverity, IncidentState


class Incident(_Base):
    """First-class incident record.

    Field docstrings mirror the JSON Schema at
    ``shared/contracts/incident/schema.json`` - the schema stays the source
    of truth; this pydantic view is the typed programmatic surface for
    ``core/incident``.

    ``incident_id`` is deterministic: UUID5(NAMESPACE_URL, sorted-tuple of
    ``correlation_keys``). Re-emitting the same key set yields the same id,
    which is the mechanism ``core/incident/registry`` uses for idempotent
    correlation.
    """

    schema_version: SemVer
    incident_id: UUID
    state: IncidentState
    severity: IncidentSeverity
    opened_at: datetime
    mitigated_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    correlation_keys: tuple[str, ...] = Field(min_length=1)
    member_event_ids: tuple[UUID, ...] = Field(min_length=1)
    related_finding_ids: tuple[str, ...] = ()
    related_action_ids: tuple[UUID, ...] = ()
    assignee_oid: str | None = None
    mitigation_summary: str | None = None
    postmortem_ref: str | None = None

    @field_validator(
        "correlation_keys",
        "member_event_ids",
        "related_finding_ids",
        "related_action_ids",
        mode="before",
    )
    @classmethod
    def _list_to_tuple(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v


__all__ = ["Incident"]
