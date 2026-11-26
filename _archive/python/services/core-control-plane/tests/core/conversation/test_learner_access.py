from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation.learner_access import project_turn_for_learner
from fdai.shared.providers.user_context import (
    ConversationTurnRecord,
    ConversationTurnRole,
    UserPreferenceRecord,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _turn() -> ConversationTurnRecord:
    return ConversationTurnRecord(
        "turn-1",
        "conversation-1",
        "principal-a",
        0,
        ConversationTurnRole.OPERATOR,
        "Private operator text.",
        NOW,
        "request-1:operator",
    )


def test_learner_gets_metadata_only_by_default() -> None:
    view = project_turn_for_learner(_turn(), preference=None)

    assert view.body is None
    assert view.turn_id == "turn-1"


def test_learner_gets_body_only_for_same_principal_explicit_opt_in() -> None:
    opted_in = UserPreferenceRecord(
        principal_id="principal-a",
        share_with_learner=True,
    )
    other_user = UserPreferenceRecord(
        principal_id="principal-b",
        share_with_learner=True,
    )

    assert project_turn_for_learner(_turn(), preference=opted_in).body == "Private operator text."
    assert project_turn_for_learner(_turn(), preference=other_user).body is None
