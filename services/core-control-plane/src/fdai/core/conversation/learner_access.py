"""Consent-gated conversation projection for Norns and other learners."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.user_context import (
    ConversationTurnRecord,
    UserPreferenceRecord,
)


@dataclass(frozen=True, slots=True)
class LearnerTurnView:
    turn_id: str
    conversation_id: str
    role: str
    recorded_at: str
    body: str | None


def project_turn_for_learner(
    turn: ConversationTurnRecord,
    *,
    preference: UserPreferenceRecord | None,
) -> LearnerTurnView:
    """Return metadata-only unless the same principal explicitly opted in."""

    share_body = (
        preference is not None
        and preference.principal_id == turn.principal_id
        and preference.share_with_learner
    )
    return LearnerTurnView(
        turn_id=turn.turn_id,
        conversation_id=turn.conversation_id,
        role=turn.role.value,
        recorded_at=turn.recorded_at.isoformat(),
        body=turn.content if share_body else None,
    )


__all__ = ["LearnerTurnView", "project_turn_for_learner"]
