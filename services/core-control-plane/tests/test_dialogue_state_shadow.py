"""Core dialogue-state shadow accounting."""

from __future__ import annotations

import logging

import pytest
from fdai_core_service.dialogue_state_shadow import ADAPTIVE_HISTORY_WINDOW, DialogueStateShadow
from fdai_service_contracts.semantic_turn import SemanticPriorTurn

SECRET = "고혈압 SECRET-CONTENT"


def _turns(count: int) -> list[SemanticPriorTurn]:
    return [
        SemanticPriorTurn(
            role="user" if index % 2 == 0 else "assistant", content=f"{SECRET} {index}"
        )
        for index in range(count)
    ]


def test_turns_beyond_the_adaptive_window_are_accounted_not_dropped() -> None:
    state = DialogueStateShadow().observe(session_id="s1", prior_turns=_turns(12))

    assert state is not None
    assert state.source_turn_count == 12
    assert len(state.kept_turn_ids) == ADAPTIVE_HISTORY_WINDOW
    assert state.compacted_turn_ids == tuple(f"s1:prior:{index}" for index in range(4))
    assert state.tier == "T0" and state.fallback_reason == "t1_unconfigured"
    assert state.execution_authority is False


@pytest.mark.parametrize("count", [0, 1, ADAPTIVE_HISTORY_WINDOW])
def test_nothing_is_reported_when_the_window_holds_every_turn(count: int) -> None:
    assert DialogueStateShadow().observe(session_id="s1", prior_turns=_turns(count)) is None


def test_logged_evidence_is_content_free(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="fdai_core_service.dialogue_state_shadow"):
        DialogueStateShadow().observe(session_id="s1", prior_turns=_turns(12))

    record = next(item for item in caplog.records if item.message == "dialogue_state_shadow")
    assert record.compacted_turns == 4 and record.kept_turns == 8  # type: ignore[attr-defined]
    assert "SECRET" not in caplog.text


def test_delivered_state_is_compared_with_core_accounting(caplog: pytest.LogCaptureFixture) -> None:
    turns = _turns(12)
    local = DialogueStateShadow().observe(session_id="s1", prior_turns=turns)
    assert local is not None
    other = DialogueStateShadow().observe(session_id="s2", prior_turns=turns)
    assert other is not None

    with caplog.at_level(logging.INFO, logger="fdai_core_service.dialogue_state_shadow"):
        DialogueStateShadow().observe(session_id="s1", prior_turns=turns, delivered=local)
        DialogueStateShadow().observe(session_id="s1", prior_turns=turns, delivered=other)
        DialogueStateShadow().observe(session_id="s1", prior_turns=turns)

    flags = [
        (record.delivered, record.delivered_matches)  # type: ignore[attr-defined]
        for record in caplog.records
        if record.message == "dialogue_state_shadow"
    ]
    assert flags == [(True, True), (True, False), (False, None)]
