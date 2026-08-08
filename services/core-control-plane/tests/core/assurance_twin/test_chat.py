"""Tests for :mod:`fdai.core.assurance_twin.chat`."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.core.assurance_twin.chat import (
    ChatMessage,
    ChatRole,
    ChatSession,
    GroundingRequiredError,
    InMemoryChatSessionStore,
    append_assistant_abstain,
    append_assistant_answer,
    append_user_question,
)
from fdai.shared.contracts.models import CeilingRole


def _session() -> ChatSession:
    return ChatSession.new(
        session_id="s-1",
        caller_id="user@example.com",
        caller_role=CeilingRole.APPROVER,
        declared_purposes=frozenset({"audit-review"}),
        correlation_id="corr-1",
    )


def test_session_new_populates_defaults() -> None:
    s = _session()
    assert s.session_id == "s-1"
    assert s.caller_role is CeilingRole.APPROVER
    assert s.declared_purposes == frozenset({"audit-review"})
    assert s.messages == ()
    assert s.created_at.tzinfo is UTC


def test_append_user_question_returns_new_snapshot() -> None:
    s0 = _session()
    s1 = append_user_question(s0, text="What changed on rg-a in the last day?")
    # Immutability: original unchanged.
    assert s0.messages == ()
    assert len(s1.messages) == 1
    assert s1.messages[0].role is ChatRole.USER


def test_append_user_question_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        append_user_question(_session(), text="   ")


def test_append_assistant_answer_requires_grounding() -> None:
    with pytest.raises(GroundingRequiredError):
        append_assistant_answer(_session(), text="answer", grounding=())


def test_append_assistant_answer_ships_grounding_in_message() -> None:
    s = append_assistant_answer(
        _session(),
        text="Two VMs changed.",
        grounding=("Resource[type=compute.vm].props.tags",),
    )
    (msg,) = s.messages
    assert msg.role is ChatRole.ASSISTANT
    assert msg.grounding == ("Resource[type=compute.vm].props.tags",)
    assert msg.abstain_reason is None


def test_append_assistant_abstain_records_reason_and_empty_grounding() -> None:
    s = append_assistant_abstain(_session(), reason="grounding_unavailable")
    (msg,) = s.messages
    assert msg.role is ChatRole.ASSISTANT
    assert msg.grounding == ()
    assert msg.abstain_reason == "grounding_unavailable"
    assert msg.text == ""


def test_append_assistant_abstain_rejects_empty_reason() -> None:
    with pytest.raises(ValueError):
        append_assistant_abstain(_session(), reason="")


def test_as_json_round_trip_via_stdlib_json() -> None:
    s = append_user_question(_session(), text="q")
    s = append_assistant_answer(s, text="a", grounding=("Path.q",))

    import json

    payload = json.loads(json.dumps(s.as_json()))
    assert payload["session_id"] == "s-1"
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["grounding"] == ["Path.q"]


def test_in_memory_store_round_trip() -> None:
    async def _run() -> None:
        store = InMemoryChatSessionStore()
        s = _session()
        s = append_user_question(s, text="hi")
        await store.save(s)
        loaded = await store.load("s-1")
        assert loaded is not None
        assert loaded.messages == s.messages
        missing = await store.load("s-does-not-exist")
        assert missing is None

    asyncio.run(_run())


def test_message_at_serialises_iso_format() -> None:
    msg = ChatMessage(
        role=ChatRole.USER,
        text="q",
        at=datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC),
    )
    assert msg.as_json()["at"].endswith("+00:00")


def test_session_with_message_is_pure() -> None:
    s0 = _session()
    m = ChatMessage(role=ChatRole.USER, text="q", at=datetime.now(tz=UTC))
    s1 = s0.with_message(m)
    # `frozen=True` - s0 stays untouched.
    assert s0.messages == ()
    assert s1.messages == (m,)
