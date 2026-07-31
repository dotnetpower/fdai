"""Off-path coordinator for deterministic and semantic turn assessment."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.conversation_assurance.consensus import MixedFamilyAssuranceReviewer
from fdai.core.conversation_assurance.deterministic import assess_deterministically
from fdai.core.conversation_assurance.ledger import ConversationAssuranceLedger
from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssessmentState,
    AssuranceDecision,
    AssuranceVerdict,
    TurnAssessmentInput,
)


class ConversationAssuranceCoordinator:
    """Assess and append one completed turn without changing its response."""

    def __init__(
        self,
        *,
        ledger: ConversationAssuranceLedger,
        reviewer: MixedFamilyAssuranceReviewer | None,
        rubric_version: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not rubric_version.strip():
            raise ValueError("assurance rubric_version MUST be non-empty")
        self._ledger = ledger
        self._reviewer = reviewer
        self._rubric_version = rubric_version
        self._now = now or (lambda: datetime.now(tz=UTC))

    async def assess(self, turn: TurnAssessmentInput) -> AssessmentRecord:
        deterministic = assess_deterministically(turn)
        model_set_digest = self._reviewer.model_set_digest if self._reviewer else "none"
        assessment_id = _assessment_id(
            turn,
            rubric_version=self._rubric_version,
            model_set_digest=model_set_digest,
        )
        existing = await self._ledger.get_assessment(
            principal_scope=turn.principal_scope,
            assessment_id=assessment_id,
        )
        if existing is not None:
            return existing
        if deterministic.verdict is not None:
            decision = AssuranceDecision(
                verdict=deterministic.verdict,
                content_score=(100.0 if deterministic.verdict is AssuranceVerdict.PASS else 0.0),
                confidence=(
                    1.0 if deterministic.verdict is not AssuranceVerdict.INCONCLUSIVE else 0.0
                ),
                reasons=deterministic.reasons,
            )
        elif self._reviewer is None:
            decision = AssuranceDecision(
                verdict=AssuranceVerdict.INCONCLUSIVE,
                content_score=0.0,
                confidence=0.0,
                reasons=("mixed_family_reviewer_unavailable",),
            )
        else:
            decision = await self._reviewer.review(turn)
        state = (
            AssessmentState.DEFERRED
            if "model_budget_deferred" in decision.reasons
            else AssessmentState.COMPLETED
        )
        record = AssessmentRecord(
            assessment_id=assessment_id,
            turn_id=turn.turn_id,
            conversation_id=turn.conversation_id,
            principal_scope=turn.principal_scope,
            question_digest=turn.question_digest,
            answer_digest=turn.answer_digest,
            evidence_manifest_digest=turn.evidence_manifest_digest,
            rubric_version=self._rubric_version,
            model_set_digest=model_set_digest,
            decision=decision,
            assessed_at=self._now(),
            state=state,
        )
        created = await self._ledger.append_assessment(record)
        if created:
            return record
        stored = await self._ledger.get_assessment(
            principal_scope=turn.principal_scope,
            assessment_id=assessment_id,
        )
        if stored is None:
            raise RuntimeError("assurance assessment lost after idempotent append")
        return stored


def _assessment_id(
    turn: TurnAssessmentInput,
    *,
    rubric_version: str,
    model_set_digest: str,
) -> str:
    material = "\0".join(
        (
            turn.turn_id,
            turn.question_digest,
            turn.answer_digest,
            turn.evidence_manifest_digest,
            rubric_version,
            model_set_digest,
        )
    )
    return "conversation-assessment:" + hashlib.sha256(material.encode()).hexdigest()


__all__ = ["ConversationAssuranceCoordinator"]
