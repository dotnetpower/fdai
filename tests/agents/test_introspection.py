"""Unit tests for the conversational-port introspection primitives."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    INTROSPECTION_ERROR,
    capability_facts,
    capability_sentence,
    capped_list,
    is_action_intent,
    mentioned,
)
from fdai.agents._framework.pantheon import _MUNINN, _NJORD, _SAGA


class TestActionIntentGuard:
    """agent-pantheon.md 7.7: the port describes actions, never runs them."""

    def test_interrogatives_are_not_action_intent(self) -> None:
        for question in (
            "what is the cost of rg-abc",
            "why was this action denied",
            "who executed correlation c-1",
            "show me the audit log",
            "list pending approvals",
            "how much capacity is left",
        ):
            assert is_action_intent(question) is False

    def test_leading_command_verbs_are_action_intent(self) -> None:
        for question in (
            "restart vm-1",
            "delete rg-abc",
            "scale the cluster up",
            "failover to secondary",
            "approve correlation c-1",
        ):
            assert is_action_intent(question) is True

    def test_polite_prefix_is_stripped_before_the_verb(self) -> None:
        assert is_action_intent("please restart vm-1") is True
        assert is_action_intent("can you delete rg-abc") is True
        assert is_action_intent("could you tell me the cost") is False

    def test_korean_imperatives_are_action_intent(self) -> None:
        assert is_action_intent("vm-1 재시작해줘") is True
        assert is_action_intent("storage-1을 삭제해 주세요") is True
        assert is_action_intent("db-1을 재부팅해 주십시오") is True
        assert is_action_intent("재시작 상태를 확인하고 vm-1을 재시작해줘") is True

    def test_korean_action_questions_remain_introspection(self) -> None:
        assert is_action_intent("vm-1 재시작 상태가 뭐야?") is False
        assert is_action_intent("storage-1 삭제 이력을 보여줘") is False
        assert is_action_intent("장애 조치 결과를 설명해줘") is False

    def test_empty_question_is_not_action_intent(self) -> None:
        assert is_action_intent("") is False
        assert is_action_intent("???") is False

    def test_ambiguous_verb_with_question_mark_is_introspection(self) -> None:
        # Verbs that double as nouns are commands only when imperative.
        for question in (
            "set of pending approvals?",
            "run status?",
            "update history?",
            "start time of the run?",
        ):
            assert is_action_intent(question) is False

    def test_ambiguous_verb_with_interrogative_marker_is_introspection(self) -> None:
        assert is_action_intent("run which experiments completed") is False
        assert is_action_intent("stop what is the condition") is False

    def test_ambiguous_verb_imperative_is_still_action(self) -> None:
        assert is_action_intent("update the rule threshold") is True
        assert is_action_intent("stop the service") is True
        assert is_action_intent("run the experiment now") is True

    def test_long_question_is_bounded(self) -> None:
        # A pathological question must not blow up tokenization; the leading
        # verb is still read and matching still terminates.
        pathological = "restart " + "x" * 100_000
        assert is_action_intent(pathological) is True
        assert mentioned(pathological, ["y"]) == []


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
        assert mentioned("inspect rule.id-extra", ["rule.id", "rule.id-extra"]) == [
            "rule.id-extra"
        ]

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
