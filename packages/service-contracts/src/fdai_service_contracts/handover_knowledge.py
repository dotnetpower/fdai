"""Content-free handover source notices and inert owner dispositions, not catalog authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KNOWLEDGE_SOURCE_EVENT = "knowledge.handover.source_observed.v1"
KNOWLEDGE_KIND = "handover_knowledge"
SOURCE_PREFIXES = {"core": "handover_goal:goal:", "operator": "operator-handover-goal:"}
_Ref = Annotated[
    str, Field(strict=True, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:/-]+$")
]
_Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


def knowledge_source_digest(record: Mapping[str, Any]) -> str:
    """Hash exact relevant source bytes; private subjects and review identities never leave here."""
    fields = (
        "goal_id",
        "assignment_case_id",
        "subject_ref",
        "agent_name",
        "scope_ref",
        "prompt_ref",
        "priority",
        "state",
        "revision",
        "source_revision",
        "evidence",
        "checklist_version",
        "required_slots",
        "slot_exemptions",
        "high_impact",
        "owner_review",
        "backup_review",
    )
    content = {key: record[key] for key in fields if key in record}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 65_536:
        raise ValueError("handover source exceeds the bounded metadata envelope")
    return hashlib.sha256(encoded).hexdigest()


class HandoverKnowledgeNotice(BaseModel):
    """Request revalidation of one source revision during one fixed five-minute window."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    source: Literal["core", "operator"]
    goal_id: _Ref
    goal_revision: Annotated[int, Field(strict=True, ge=1)]
    source_digest: _Digest
    check_epoch: Annotated[int, Field(strict=True, ge=0)]

    @property
    def source_key(self) -> str:
        return SOURCE_PREFIXES[self.source] + self.goal_id

    @property
    def source_id(self) -> str:
        return hashlib.sha256(self.source_key.encode()).hexdigest()

    @property
    def notice_id(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def require_current(self, at: datetime) -> None:
        """A clock rollback or an expired check cannot authorize a later source disposition."""
        if at.utcoffset() is None or int(at.timestamp()) // 300 != self.check_epoch:
            raise ValueError("handover source check window is no longer current")


class HandoverKnowledgeDecision(BaseModel):
    """An owner-attributed review disposition that can never promote or execute."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    notice: HandoverKnowledgeNotice
    disposition: Literal["admitted", "gap", "held", "conflict", "withdrawn"]
    reason: Literal[
        "source_admitted",
        "checklist_incomplete",
        "source_unavailable",
        "source_changed",
        "source_withdrawn",
        "evidence_conflict",
        "clarification_required",
        "binding_unavailable",
        "check_expired",
        "review_required",
        "publication_held",
    ]
    evidence_refs: Annotated[tuple[_Ref, ...], Field(max_length=64)] = ()
    evidence_digests: Annotated[tuple[_Digest, ...], Field(max_length=64)] = ()
    review_required: Literal[True] = True
    may_promote: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("review_required", "may_promote", "execution_authority", mode="before")
    @classmethod
    def _strict_flags(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("handover knowledge authority flags MUST be booleans")
        return value

    @model_validator(mode="after")
    def _evidence_shape(self) -> HandoverKnowledgeDecision:
        if len(self.evidence_refs) != len(self.evidence_digests):
            raise ValueError("handover source evidence references and digests must align")
        if self.disposition == "admitted" and not self.evidence_refs:
            raise ValueError("admitted handover source requires document evidence")
        allowed = {
            "admitted": {"source_admitted", "review_required"},
            "gap": {"checklist_incomplete"},
            "withdrawn": {"source_withdrawn"},
            "conflict": {"evidence_conflict", "clarification_required"},
            "held": {
                "source_unavailable",
                "source_changed",
                "binding_unavailable",
                "check_expired",
                "publication_held",
            },
        }
        if self.reason not in allowed[self.disposition]:
            raise ValueError("handover disposition does not match its reason")
        if self.disposition != "admitted" and self.evidence_refs:
            raise ValueError("held handover dispositions cannot disclose document references")
        return self


def notice_for_source(
    record: Mapping[str, Any], *, source: Literal["core", "operator"], at: datetime
) -> HandoverKnowledgeNotice:
    """Create only a request for independent source checking, never an admissibility result."""
    if at.utcoffset() is None:
        raise ValueError("handover source observation time MUST include a timezone")
    digest = record.get("source_digest") or knowledge_source_digest(record)
    return HandoverKnowledgeNotice(
        source=source,
        goal_id=record["goal_id"],
        goal_revision=record["revision"],
        source_digest=digest,
        check_epoch=int(at.timestamp()) // 300,
    )


def notice_deadline(notice: HandoverKnowledgeNotice) -> datetime:
    """Return the fixed exclusive end of this request's source-check window."""
    return datetime.fromtimestamp(notice.check_epoch * 300, UTC) + timedelta(minutes=5)


__all__ = [
    "KNOWLEDGE_KIND",
    "KNOWLEDGE_SOURCE_EVENT",
    "SOURCE_PREFIXES",
    "HandoverKnowledgeDecision",
    "HandoverKnowledgeNotice",
    "knowledge_source_digest",
    "notice_deadline",
    "notice_for_source",
]
