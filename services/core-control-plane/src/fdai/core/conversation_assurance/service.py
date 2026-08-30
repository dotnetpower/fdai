"""Off-path coordinator for deterministic and semantic turn assessment."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.conversation_assurance.consensus import MixedFamilyAssuranceReviewer
from fdai.core.conversation_assurance.deterministic import assess_deterministically
from fdai.core.conversation_assurance.ledger import ConversationAssuranceLedger
from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssessmentState,
    AssuranceDecision,
    AssuranceVerdict,
    EvaluatorOutput,
    TurnAssessmentInput,
)
from fdai.core.conversation_assurance.pantheon_scorecard import PantheonTurnDiagnostic
from fdai.core.conversation_assurance.quality_latency import (
    LatencyEnvironment,
    LatencySampleOutcome,
    LatencyStage,
    LatencyStageReceipt,
    latency_sample_from_stage_receipt,
)


@dataclass(frozen=True, slots=True)
class AssuranceReview:
    """One bounded review result retained until its diagnostic is assembled."""

    decision: AssuranceDecision
    model_set_digest: str
    evaluator_outputs: tuple[EvaluatorOutput, ...] = ()


class ConversationAssuranceCoordinator:
    """Assess and append one completed turn without changing its response."""

    def __init__(
        self,
        *,
        ledger: ConversationAssuranceLedger,
        reviewer: MixedFamilyAssuranceReviewer | None,
        rubric_version: str,
        now: Callable[[], datetime] | None = None,
        deterministic_timing_environment: LatencyEnvironment | None = None,
        deterministic_timing_sink: Callable[[LatencyStageReceipt], None] | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        if not rubric_version.strip():
            raise ValueError("assurance rubric_version MUST be non-empty")
        self._ledger = ledger
        self._reviewer = reviewer
        self._rubric_version = rubric_version
        self._now = now or (lambda: datetime.now(tz=UTC))
        if (deterministic_timing_environment is None) is not (deterministic_timing_sink is None):
            raise ValueError(
                "deterministic timing environment and sink MUST be configured together"
            )
        self._deterministic_timing_environment = deterministic_timing_environment
        self._deterministic_timing_sink = deterministic_timing_sink
        self._monotonic_ns = monotonic_ns or time.monotonic_ns

    async def assess(
        self,
        turn: TurnAssessmentInput,
        *,
        pantheon_diagnostic: PantheonTurnDiagnostic | None = None,
    ) -> AssessmentRecord:
        model_set_digest = self._reviewer.model_set_digest if self._reviewer else "none"
        assessment_id = _assessment_id(
            turn,
            rubric_version=self._rubric_version,
            model_set_digest=model_set_digest,
            pantheon_diagnostic=pantheon_diagnostic,
        )
        existing = await self._ledger.get_assessment(
            principal_scope=turn.principal_scope,
            assessment_id=assessment_id,
        )
        if existing is not None:
            return existing
        review = await self.review(turn)
        return await self.persist(
            turn,
            review,
            pantheon_diagnostic=pantheon_diagnostic,
        )

    async def review(self, turn: TurnAssessmentInput) -> AssuranceReview:
        """Evaluate one turn once without persisting an incomplete diagnostic."""

        if self._deterministic_timing_sink is None:
            deterministic = assess_deterministically(turn)
        else:
            started_monotonic_ns = self._monotonic_ns()
            deterministic = assess_deterministically(turn)
            completed_monotonic_ns = self._monotonic_ns()
            self._record_deterministic_timing(
                turn,
                started_monotonic_ns=started_monotonic_ns,
                completed_monotonic_ns=completed_monotonic_ns,
            )
        model_set_digest = self._reviewer.model_set_digest if self._reviewer else "none"
        if deterministic.verdict is not None:
            decision = AssuranceDecision(
                verdict=deterministic.verdict,
                content_score=(100.0 if deterministic.verdict is AssuranceVerdict.PASS else 0.0),
                confidence=(
                    1.0 if deterministic.verdict is not AssuranceVerdict.INCONCLUSIVE else 0.0
                ),
                reasons=deterministic.reasons,
            )
            outputs: tuple[EvaluatorOutput, ...] = ()
        elif self._reviewer is None:
            decision = AssuranceDecision(
                verdict=AssuranceVerdict.INCONCLUSIVE,
                content_score=0.0,
                confidence=0.0,
                reasons=("mixed_family_reviewer_unavailable",),
            )
            outputs = ()
        else:
            decision, outputs = await self._reviewer.review_with_outputs(turn)
        return AssuranceReview(
            decision=decision,
            model_set_digest=model_set_digest,
            evaluator_outputs=outputs,
        )

    async def persist(
        self,
        turn: TurnAssessmentInput,
        review: AssuranceReview,
        *,
        pantheon_diagnostic: PantheonTurnDiagnostic | None = None,
    ) -> AssessmentRecord:
        """Append one reviewed turn after all correlated diagnostics are complete."""

        decision = review.decision
        if pantheon_diagnostic is not None:
            decision = AssuranceDecision(
                verdict=decision.verdict,
                content_score=decision.content_score,
                confidence=decision.confidence,
                criteria=decision.criteria,
                reasons=decision.reasons,
                evaluator_identities=decision.evaluator_identities,
                disagreement=decision.disagreement,
                model_calls=decision.model_calls,
                prompt_tokens=decision.prompt_tokens,
                completion_tokens=decision.completion_tokens,
                cost_microusd=decision.cost_microusd,
                pantheon_diagnostic=pantheon_diagnostic,
            )
        assessment_id = _assessment_id(
            turn,
            rubric_version=self._rubric_version,
            model_set_digest=review.model_set_digest,
            pantheon_diagnostic=pantheon_diagnostic,
        )
        existing = await self._ledger.get_assessment(
            principal_scope=turn.principal_scope,
            assessment_id=assessment_id,
        )
        if existing is not None:
            return existing
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
            model_set_digest=review.model_set_digest,
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

    def _record_deterministic_timing(
        self,
        turn: TurnAssessmentInput,
        *,
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        environment = self._deterministic_timing_environment
        sink = self._deterministic_timing_sink
        if environment is None or sink is None:
            return
        receipt = LatencyStageReceipt(
            stage=LatencyStage.DETERMINISTIC_VERIFICATION,
            environment=environment,
            observed_at=self._now().isoformat(),
            started_monotonic_ns=started_monotonic_ns,
            completed_monotonic_ns=completed_monotonic_ns,
            timestamp_authority="conversation-assurance-monotonic",
            trace_digest=_digest_parts(turn.conversation_id, turn.turn_id),
            provenance_digest=_digest_parts(
                turn.question_digest,
                turn.answer_digest,
                turn.evidence_manifest_digest,
                self._rubric_version,
            ),
            outcome=LatencySampleOutcome.COMPLETED,
        )
        latency_sample_from_stage_receipt(receipt)
        sink(receipt)


def _assessment_id(
    turn: TurnAssessmentInput,
    *,
    rubric_version: str,
    model_set_digest: str,
    pantheon_diagnostic: PantheonTurnDiagnostic | None,
) -> str:
    material = "\0".join(
        (
            turn.turn_id,
            turn.question_digest,
            turn.answer_digest,
            turn.evidence_manifest_digest,
            turn.verification_reason_code,
            turn.verification_route_id or "",
            str(turn.evidence_complete),
            rubric_version,
            model_set_digest,
            pantheon_diagnostic.content_digest if pantheon_diagnostic is not None else "",
        )
    )
    return "conversation-assessment:" + hashlib.sha256(material.encode()).hexdigest()


def _digest_parts(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


__all__ = ["AssuranceReview", "ConversationAssuranceCoordinator"]
