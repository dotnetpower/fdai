"""Actual conversation admission enforces durable fatigue and current ownership."""

from __future__ import annotations

import asyncio
import runpy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationProposal,
    PrincipalScope,
)
from fdai_service_contracts import OperatorRole

_support = runpy.run_path(str(Path(__file__).with_name("test_handover_runtime.py")))
_runtime, _SUBJECT, _NOW = (_support[name] for name in ("_runtime", "_SUBJECT", "_NOW"))


async def _setup():
    runtime, store, reader = _runtime()
    invitation = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login",
    )
    assert invitation is not None
    return runtime, store, reader, invitation["goal_id"]


def _proposal(
    goal,
    *,
    turn=1,
    session="conversation-one",
    prompt="Explain the remaining evidence.",
):
    return ConversationProposal(
        operation="chat.stream",
        scope=PrincipalScope(_SUBJECT, frozenset({"Reader"})),
        idempotency_key=f"turn-{turn}",
        body={"prompt": prompt, "session_id": session, "handover_goal_id": goal},
    )


async def test_three_unique_turns_maximum_including_concurrent_fourth():
    runtime, _, _, goal = await _setup()
    results = await asyncio.gather(
        *(runtime.bind_conversation(_proposal(goal, turn=turn)) for turn in range(1, 5)),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ConversationProposal) for item in results) == 3
    assert sum(isinstance(item, ConversationBoundaryError) for item in results) == 1


async def test_replay_preserves_fixed_deadline_and_does_not_consume_another_question():
    runtime, _, _, goal = await _setup()
    proposal = _proposal(goal)
    first = await runtime.bind_conversation(proposal)
    later = replace(runtime, clock=lambda: _NOW + timedelta(seconds=10))
    assert await later.bind_conversation(proposal) == first
    await later.bind_conversation(_proposal(goal, turn=2))
    await later.bind_conversation(_proposal(goal, turn=3))
    with pytest.raises(ConversationBoundaryError, match="question"):
        await later.bind_conversation(_proposal(goal, turn=4))


async def test_changed_prompt_cannot_reuse_a_budget_reservation():
    runtime, _, _, goal = await _setup()
    await runtime.bind_conversation(_proposal(goal))
    with pytest.raises(ConversationBoundaryError, match="replay"):
        await runtime.bind_conversation(_proposal(goal, prompt="A different request."))


async def test_non_sliding_five_minutes_and_final_turn_deadline():
    runtime, _, _, goal = await _setup()
    await runtime.bind_conversation(_proposal(goal))
    last_minute = replace(runtime, clock=lambda: _NOW + timedelta(seconds=299))
    bound = await last_minute.bind_conversation(_proposal(goal, turn=2))
    assert bound.body["deadline_at"] == (_NOW + timedelta(minutes=5)).isoformat()
    expired = replace(runtime, clock=lambda: _NOW + timedelta(minutes=5))
    with pytest.raises(ConversationBoundaryError, match="time budget"):
        await expired.bind_conversation(_proposal(goal, turn=3))


async def test_one_active_session_survives_restart_and_cannot_switch_goals():
    runtime, store, _, goal = await _setup()
    await runtime.bind_conversation(_proposal(goal))
    restarted = replace(runtime)
    with pytest.raises(ConversationBoundaryError, match="another.*active"):
        await restarted.bind_conversation(_proposal(goal, session="other-conversation"))
    other = "a" * 64
    store.states[f"operator-handover-goal:{other}"] = {
        **store.states[f"operator-handover-goal:{goal}"],
        "goal_id": other,
    }
    with pytest.raises(ConversationBoundaryError, match="another goal"):
        await restarted.bind_conversation(_proposal(other, turn=2))


async def test_ended_session_cannot_reopen_after_another_session():
    runtime, _, _, goal = await _setup()
    await runtime.bind_conversation(_proposal(goal))
    later = replace(runtime, clock=lambda: _NOW + timedelta(minutes=6))
    await later.bind_conversation(_proposal(goal, session="session-two"))
    ended = replace(runtime, clock=lambda: _NOW + timedelta(minutes=12))
    with pytest.raises(ConversationBoundaryError, match="ended"):
        await ended.bind_conversation(_proposal(goal, turn=2))


async def test_actual_handover_sessions_have_an_independent_weekly_ceiling():
    runtime, _, _, goal = await _setup()
    for session, minutes in (("session-one", 0), ("session-two", 6)):
        await replace(
            runtime, clock=lambda minutes=minutes: _NOW + timedelta(minutes=minutes)
        ).bind_conversation(_proposal(goal, session=session))
    later = replace(runtime, clock=lambda: _NOW + timedelta(minutes=12))
    with pytest.raises(ConversationBoundaryError, match="weekly"):
        await later.bind_conversation(_proposal(goal, session="session-three"))


@pytest.mark.parametrize("change", ["removed", "revision", "inactive", "busy"])
async def test_every_conversation_and_replay_rechecks_current_owner_and_workload(change):
    runtime, _, reader, goal = await _setup()
    proposal = _proposal(goal)
    await runtime.bind_conversation(proposal)
    if change == "removed":
        reader.mapped = False
    elif change == "revision":
        reader.source_revision = "revision-new"
    elif change == "inactive":
        reader.active = False
    else:
        runtime.activity_guard.allowed = False
    with pytest.raises(ConversationBoundaryError):
        await runtime.bind_conversation(proposal)


async def test_accepted_goals_never_start_conversations_and_ordinary_console_is_unchanged():
    from fdai_service_contracts.handover_checklist import HANDOVER_SLOTS, checklist_digest

    runtime, store, _, goal = await _setup()
    accepted = store.states[f"operator-handover-goal:{goal}"]
    accepted.update(
        state="accepted",
        revision=9,
        slot_exemptions={slot: "reason:reviewed" for slot in HANDOVER_SLOTS},
    )
    accepted["owner_review"] = {
        "reviewer_ref": "human:owner",
        "goal_revision": 7,
        "evidence_digest": checklist_digest(accepted),
        "reviewed_at": _NOW.isoformat(),
    }
    accepted["backup_review"] = {
        **accepted["owner_review"],
        "reviewer_ref": "human:backup",
        "goal_revision": 8,
    }
    with pytest.raises(ConversationBoundaryError, match="no longer conversational"):
        await runtime.bind_conversation(_proposal(goal))
    ordinary = replace(
        _proposal(goal),
        body={"prompt": "Read current state.", "session_id": "ordinary"},
    )
    assert await runtime.bind_conversation(ordinary) is ordinary


async def test_clock_rollback_cannot_extend_a_running_session():
    runtime, _, _, goal = await _setup()
    await runtime.bind_conversation(_proposal(goal))
    earlier = replace(runtime, clock=lambda: _NOW - timedelta(seconds=1))
    with pytest.raises(ConversationBoundaryError, match="clock"):
        await earlier.bind_conversation(_proposal(goal, turn=2))
