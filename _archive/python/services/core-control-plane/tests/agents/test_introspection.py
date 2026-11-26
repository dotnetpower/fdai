"""Unit tests for the conversational-port introspection primitives."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    INTROSPECTION_ERROR,
    capability_facts,
    capability_sentence,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _MUNINN, _NJORD, _SAGA


def test_structured_action_posture_requires_typed_pipeline() -> None:
    agent = Agent(spec=_NJORD)

    result = asyncio.run(
        agent.on_conversation_turn(
            "operator request",
            {"semantic_action_posture": "draft_only"},
        )
    )

    assert result["requires_typed_pipeline"] is True
    assert result["abstain_reason"] == "requires_typed_pipeline"


class TestMentioned:
    def test_matches_named_candidate_tokens(self) -> None:
        assert mentioned("cost for rg-abc please", ["rg-abc", "rg-xyz"]) == ["rg-abc"]

    def test_is_case_insensitive(self) -> None:
        assert mentioned("what about RG-ABC", ["rg-abc"]) == ["rg-abc"]

    def test_matches_dotted_and_underscored_identifiers(self) -> None:
        assert mentioned(
            "compare my_resource with rule.id.",
            ["my_resource", "rule.id", "other"],
        ) == ["my_resource", "rule.id"]

    def test_does_not_match_identifier_prefixes(self) -> None:
        assert mentioned("inspect rule.id-extra", ["rule.id", "rule.id-extra"]) == ["rule.id-extra"]

    def test_preserves_candidate_order(self) -> None:
        assert mentioned("a and b", ["b", "a"]) == ["b", "a"]

    def test_no_match_returns_empty(self) -> None:
        assert mentioned("nothing relevant here", ["rg-abc"]) == []


class TestCappedList:
    """Bounds facts payload size and incidental identifier exposure."""

    def test_caps_at_twenty_items(self) -> None:
        assert len(capped_list(range(100))) == 20

    def test_short_list_unchanged(self) -> None:
        assert capped_list(["a", "b"]) == ["a", "b"]

    def test_items_are_stringified(self) -> None:
        assert capped_list([1, 2]) == ["1", "2"]


class TestCapability:
    def test_capability_facts_mirror_the_spec(self) -> None:
        facts = capability_facts(_NJORD)
        assert facts["agent"] == "Njord"
        assert facts["layer"] == "domain"
        assert facts["owns"] == list(_NJORD.owns)
        assert facts["question_domains"] == list(_NJORD.question_domains)

    def test_capability_sentence_names_the_agent(self) -> None:
        sentence = capability_sentence(_SAGA)
        assert "Saga" in sentence
        assert "governance" in sentence


class TestBaseIntrospect:
    """The base conversational port answers a spec-grounded self-description."""

    def test_base_introspect_falls_back_to_capability(self) -> None:
        agent = Agent(spec=_MUNINN)
        result = asyncio.run(agent.introspect("what can you do", {}))
        assert result.answer is not None
        assert "Muninn" in result.answer
        assert result.abstain_reason is None
        assert result.facts["agent"] == "Muninn"
        assert result.facts["owns"] == list(_MUNINN.owns)

    def test_conversation_port_isolates_a_raising_introspect(self) -> None:
        # One agent's introspection bug must not crash the shared port: it
        # degrades to an honest abstain (H2).
        agent = Agent(spec=_MUNINN)

        async def boom(question: str, context: dict) -> object:
            raise RuntimeError("secret-bearing failure")

        agent.introspect = boom  # type: ignore[method-assign]
        result = asyncio.run(agent.on_conversation_turn("state?", {}))
        assert result["answer"] is None
        assert result["abstain_reason"] == INTROSPECTION_ERROR
