from __future__ import annotations

import pytest
from fdai.shared.contracts import KnowledgeEvidenceEvent, KnowledgeEvidenceEventType
from pydantic import ValidationError


def test_candidate_events_are_content_free_and_review_required() -> None:
    event = KnowledgeEvidenceEvent(
        event_type=KnowledgeEvidenceEventType.RULE_CANDIDATE,
        goal_ref="goal-1",
        evidence_refs=("doc:document-1:version-1#line-7",),
        evidence_digest="a" * 64,
        producer_agent="Norns",
        reason_code="recurring_operational_pattern",
    )

    assert event.content_included is False
    assert event.requires_review is True
    assert "text" not in event.model_dump()


def test_candidate_event_cannot_claim_promotion_or_include_content() -> None:
    with pytest.raises(ValidationError):
        KnowledgeEvidenceEvent.model_validate(
            {
                "event_type": "knowledge.ontology-candidate.proposed",
                "goal_ref": "goal-1",
                "evidence_refs": ["doc:document-1:version-1#line-7"],
                "evidence_digest": "a" * 64,
                "producer_agent": "Mimir",
                "reason_code": "typed_concept_candidate",
                "content_included": True,
                "requires_review": False,
                "text": "untrusted content",
            }
        )
