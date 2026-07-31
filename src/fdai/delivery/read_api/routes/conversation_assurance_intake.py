"""Bounded off-path intake from completed conversation turns."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fdai.core.conversation_assurance import (
    ConversationAssuranceCoordinator,
    TurnAssessmentInput,
    assurance_principal_scope,
)
from fdai.delivery.read_api.routes.chat_history import completed_replay_payload
from fdai.delivery.read_api.routes.post_turn_review import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
)
from fdai.shared.providers.user_context import ConversationTurnRecord


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
        config: ConversationAssuranceQueueConfig | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._delegate = delegate
        self._config = config or ConversationAssuranceQueueConfig()
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
            return False
        turn = _assessment_input(operator_turn, assistant_turn)
        task = asyncio.create_task(
            self._assess(turn),
            name=f"conversation-assurance:{assistant_turn.turn_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return delegated

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _assess(self, turn: TurnAssessmentInput) -> None:
        try:
            await self._coordinator.assess(turn)
        except Exception:  # noqa: BLE001 - original answer is already durable
            return


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
    evidence_manifest = verification.get("evidence_manifest")
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
        locale=str(assistant_turn.metadata.get("locale") or "en"),
        answer_model_identity=str(model) if isinstance(model, str) and model else None,
        deterministic_answer=isinstance(source, str) and source.startswith("evidence:"),
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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
