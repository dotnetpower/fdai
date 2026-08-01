"""Content-free events for governed handover evidence collaboration."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from ._base import _Base


class KnowledgeEvidenceEventType(StrEnum):
    PROPOSED = "knowledge.evidence.proposed"
    DUPLICATE = "knowledge.evidence.duplicate"
    CONFLICT = "knowledge.evidence.conflict"
    ONTOLOGY_CANDIDATE = "knowledge.ontology-candidate.proposed"
    RULE_CANDIDATE = "knowledge.rule-candidate.proposed"


class KnowledgeEvidenceEvent(_Base):
    event_type: KnowledgeEvidenceEventType
    goal_ref: Annotated[str, Field(min_length=1, max_length=256)]
    evidence_refs: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = Field(
        min_length=1,
        max_length=16,
    )
    evidence_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    producer_agent: Annotated[str, Field(min_length=1, max_length=64)]
    reason_code: Annotated[str, Field(min_length=1, max_length=128)]
    content_included: Literal[False] = False
    requires_review: Literal[True] = True


__all__ = ["KnowledgeEvidenceEvent", "KnowledgeEvidenceEventType"]
