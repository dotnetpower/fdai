"""Bounded off-path intake from completed conversation turns."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from fdai.core.conversation_assurance import (
    AdequacyReviewState,
    ConversationAssuranceCoordinator,
    ConversationAssuranceLedger,
    ConversationAssuranceLifecycleRunner,
    OntologyAdequacyInvestigator,
    OntologyAdequacyReviewSink,
    TurnAssessmentInput,
    assurance_principal_scope,
    attribute_answer_failure,
)
from fdai.delivery.operator_api.projections.conversation.terminal import completed_replay_payload
from fdai.delivery.operator_api.routes.post_turn_review import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
)
from fdai.shared.providers.user_context import ConversationTurnRecord

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConversationAssuranceQueueConfig:
    max_pending: int = 64

    def __post_init__(self) -> None:
        if not 1 <= self.max_pending <= 1_024:
            raise ValueError("conversation assurance max_pending MUST be in [1, 1024]")


class ConversationAssurancePostTurnSubmitter:
    """Fan out completed turns without delaying or changing the answer."""

    def __init__(
        self,
        *,
        coordinator: ConversationAssuranceCoordinator,
        delegate: PostTurnReviewSubmitter | None = None,
        ledger: ConversationAssuranceLedger | None = None,
        lifecycle: ConversationAssuranceLifecycleRunner | None = None,
        config: ConversationAssuranceQueueConfig | None = None,
        adequacy_investigator: OntologyAdequacyInvestigator | None = None,
        adequacy_sink: OntologyAdequacyReviewSink | None = None,
    ) -> None:
        if (ledger is None) is not (lifecycle is None):
            raise ValueError("assurance ledger and lifecycle MUST be configured together")
        if (adequacy_investigator is None) is not (adequacy_sink is None):
            raise ValueError("adequacy investigator and sink MUST be configured together")
        self._coordinator = coordinator
        self._delegate = delegate
        self._ledger = ledger
        self._lifecycle = lifecycle
        self._config = config or ConversationAssuranceQueueConfig()
        self._adequacy_investigator = adequacy_investigator
        self._adequacy_sink = adequacy_sink
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending(self) -> int:
        return len(self._tasks)

    def submit_nowait(
        self,
        *,
        operator_turn: ConversationTurnRecord,
        assistant_turn: ConversationTurnRecord,
        submission: PostTurnReviewSubmission,
    ) -> bool:
        delegated = (
            self._delegate.submit_nowait(
                operator_turn=operator_turn,
                assistant_turn=assistant_turn,
                submission=submission,
            )
            if self._delegate is not None
            else True
        )
        if len(self._tasks) >= self._config.max_pending:
            _LOG.warning(
                "conversation_assurance_queue_full",
                extra={
                    "turn_id": assistant_turn.turn_id,
                    "pending": len(self._tasks),
                    "max_pending": self._config.max_pending,
                },
            )
            return False
        turn = _assessment_input(operator_turn, assistant_turn)
        task = asyncio.create_task(
            self._assess(turn),
            name=f"conversation-assurance:{assistant_turn.turn_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if not delegated:
            _LOG.warning(
                "post_turn_review_delegate_rejected",
                extra={"turn_id": assistant_turn.turn_id},
            )
        return delegated

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _assess(self, turn: TurnAssessmentInput) -> None:
        try:
            assessment = await self._coordinator.assess(turn)
            if assessment.decision.verdict.value == "fail":
                await self._submit_adequacy_review(turn)
            if self._ledger is not None and self._lifecycle is not None:
                records = await self._ledger.list_assessments(
                    principal_scope=turn.principal_scope,
                    limit=1_000,
                )
                await self._lifecycle.run(records)
        except Exception:  # noqa: BLE001 - original answer is already durable
            _LOG.exception(
                "conversation_assurance_assessment_failed",
                extra={"turn_id": turn.turn_id},
            )

    async def _submit_adequacy_review(self, turn: TurnAssessmentInput) -> None:
        investigator = self._adequacy_investigator
        sink = self._adequacy_sink
        if investigator is None or sink is None:
            return
        attribution = attribute_answer_failure(turn)
        review = await investigator.investigate(turn, attribution)
        if review.state is AdequacyReviewState.NOT_APPLICABLE:
            return
        await sink.submit(review)


def _assessment_input(
    operator_turn: ConversationTurnRecord,
    assistant_turn: ConversationTurnRecord,
) -> TurnAssessmentInput:
    if operator_turn.principal_id != assistant_turn.principal_id:
        raise ValueError("assurance exchange principals MUST match")
    if operator_turn.conversation_id != assistant_turn.conversation_id:
        raise ValueError("assurance exchange conversations MUST match")
    payload = completed_replay_payload(assistant_turn)
    verification = _mapping(payload.get("verification"))
    evidence_manifest = _mapping(verification.get("evidence_manifest"))
    evidence_refs = _string_tuple(verification.get("evidence_refs"))
    failed_claim_ids = _string_tuple(verification.get("failed_claim_ids"))
    source = payload.get("source")
    model = payload.get("model")
    return TurnAssessmentInput(
        turn_id=assistant_turn.turn_id,
        conversation_id=assistant_turn.conversation_id,
        principal_scope=assurance_principal_scope(assistant_turn.principal_id),
        question=operator_turn.content,
        answer=assistant_turn.content,
        question_digest=_digest_text(operator_turn.content),
        answer_digest=_digest_text(assistant_turn.content),
        evidence_manifest_digest=_digest_json(evidence_manifest),
        evidence_refs=evidence_refs,
        verification_status=str(verification.get("status") or "unverified"),
        verification_authority=str(verification.get("authority") or "unavailable"),
        checks_completed=_non_negative_int(verification.get("checks_completed")),
        checks_total=_non_negative_int(verification.get("checks_total")),
        failed_claim_ids=failed_claim_ids,
        verification_reason_code=str(
            verification.get("reason_code") or "verification_reason_unavailable"
        ),
        verification_route_id=_optional_text(evidence_manifest.get("route_id")),
        evidence_complete=(
            evidence_manifest.get("complete")
            if isinstance(evidence_manifest.get("complete"), bool)
            else None
        ),
        ontology_release=_nested_text(payload, "ontology_release"),
        graph_revision=_nested_text(payload, "graph_revision"),
        locale=str(assistant_turn.metadata.get("locale") or "en"),
        answer_model_identity=str(model) if isinstance(model, str) and model else None,
        deterministic_answer=isinstance(source, str) and source.startswith("evidence:"),
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nested_text(payload: dict[str, Any], key: str) -> str | None:
    direct = _optional_text(payload.get(key))
    if direct is not None:
        return direct
    intent_graph = _mapping(payload.get("intent_graph"))
    return _optional_text(intent_graph.get(key))


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


__all__ = [
    "ConversationAssurancePostTurnSubmitter",
    "ConversationAssuranceQueueConfig",
]
