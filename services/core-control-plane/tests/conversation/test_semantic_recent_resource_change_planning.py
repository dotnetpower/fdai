"""An explicit recent-change window bounds the read; otherwise the server default applies."""

from __future__ import annotations

import pytest
from fdai.core.conversation.semantic_recent_resource_change_planning import (
    build_recent_resource_change_frame,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def _judgment() -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal(
        primary_intent="query.resource_change_activity",
        targets=(),
        requested_facets=("changed_resources",),
        confidence=0.95,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )


@pytest.mark.parametrize(
    ("utterance", "lookback_seconds"),
    [
        ("What changed in the last 24 hours?", 86_400),
        ("지난 3일 동안 변경된 리소스 알려줘", 259_200),
        ("최근 1시간 동안 변경된 리소스 알려줘", 3_600),
        ("최근 변경된 리소스 알려줘", 3_600),
    ],
)
def test_stated_window_sets_the_recent_change_lookback(
    utterance: str, lookback_seconds: int
) -> None:
    result = build_recent_resource_change_frame(_judgment(), utterance=utterance, context=())

    assert result is not None
    proposal, frame = result
    assert proposal.temporal_scope == {"lookback_seconds": lookback_seconds}
    assert frame.temporal_scope["lookback_seconds"] == lookback_seconds
