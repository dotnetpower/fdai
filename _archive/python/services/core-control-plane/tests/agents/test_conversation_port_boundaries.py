"""Round 5 conversational-port boundary regressions."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from types import MethodType
from typing import Any

import pytest
from fdai.agents import AgentToolStatus
from fdai.agents._framework.bragi_contributors import normalize_responder_answer
from fdai.agents._framework.bragi_diagnostics import attach_pantheon_diagnostics
from fdai.agents._framework.bragi_models import RoutingDecision, Turn
from fdai.agents._framework.bragi_publication import turn_event_payload
from fdai.agents._framework.bragi_routing import route_semantic_judgment
from fdai.agents._framework.conversation_prompt import ConversationSituation
from fdai.agents._framework.deliberation import _claim
from fdai.agents._framework.introspection import IntrospectionResult, agent_state_evidence_ref
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.semantic_routing import SemanticAgentRouter, SemanticRouterConfig
from fdai.agents.bragi import Bragi
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from tests.agents.semantic_judgment_support import semantic_test_boundary, semantic_test_proposal


class _SlowSemanticBoundary:
    def __init__(self) -> None:
        self.calls = 0

    def judge(self, **_kwargs: object) -> object:
        self.calls += 1
        time.sleep(0.05)
        raise AssertionError("timeout test should not consume this result")


class _CountingSemanticBoundary:
    def __init__(self) -> None:
        self.calls = 0

    def judge(self, **_kwargs: object) -> object:
        self.calls += 1
        return semantic_test_boundary().judge(**_kwargs)


class _HangingEmbedding:
    dim = len(PANTHEON_SPECS)

    async def embed(self, _text: str) -> Sequence[float]:
        await asyncio.Event().wait()
        return [0.0] * self.dim


class _HangingQueryEmbedding:
    dim = len(PANTHEON_SPECS)

    async def embed(self, text: str) -> Sequence[float]:
        for index, spec in enumerate(PANTHEON_SPECS):
            if text.startswith(f"{spec.name}\n"):
                vector = [0.0] * self.dim
                vector[index] = 1.0
                return vector
        await asyncio.Event().wait()
        return [0.0] * self.dim


def test_raw_question_text_never_selects_question_domain_owner() -> None:
    judgment = semantic_test_proposal("no canonical owner here")

    decision = route_semantic_judgment(judgment, max_contributors=2, question="help")

    assert decision.primary_agent is None
    assert decision.method == "semantic_abstain"


def test_single_exact_question_domain_does_not_fan_out_to_object_owner() -> None:
    payload = semantic_test_proposal("cost status").model_dump(mode="json")
    payload["targets"] = [
        {
            "kind": "object_type",
            "value": "CapacityForecast",
            "canonical_value": "CapacityForecast",
            "source_start": 0,
            "source_end": 16,
        }
    ]
    judgment = SemanticJudgmentProposal.model_validate(payload)

    decision = route_semantic_judgment(judgment, max_contributors=2)

    assert decision.primary_agent == "Njord"
    assert decision.contributors == ()
    assert decision.tie_break == "canonical_question_domain"


def test_deliberation_validates_question_length_before_semantic_boundary() -> None:
    boundary = _CountingSemanticBoundary()
    bragi = Bragi(semantic_judgment=boundary)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="2000"):
        asyncio.run(bragi.deliberate(question="x" * 2001, requester="Forseti"))

    assert boundary.calls == 0


def test_deliberation_validates_requester_before_semantic_boundary() -> None:
    boundary = _CountingSemanticBoundary()
    bragi = Bragi(semantic_judgment=boundary)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unknown requester"):
        asyncio.run(bragi.deliberate(question="cost status", requester="Mallory"))

    assert boundary.calls == 0


def test_bragi_ask_semantic_judgment_timeout_abstains_quickly() -> None:
    bragi = Bragi(
        semantic_judgment=_SlowSemanticBoundary(),  # type: ignore[arg-type]
        semantic_judgment_timeout_seconds=0.001,
    )

    turn = asyncio.run(
        bragi.ask(session_id="semantic-timeout", user_id="operator", question="cost status")
    )

    assert turn.primary_agent is None
    assert turn.answer["abstain_reason"] == "semantic_unavailable"
    assert turn.answer["routing_provider_status"] == "timeout"


def test_semantic_router_query_embedding_timeout_abstains() -> None:
    router = SemanticAgentRouter(
        embedding_model=_HangingQueryEmbedding(),  # type: ignore[arg-type]
        specs=PANTHEON_SPECS,
        config=SemanticRouterConfig(embedding_timeout_seconds=0.001),
    )

    decision = asyncio.run(
        router.route(
            "ambiguous question",
            t0=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            max_contributors=2,
        )
    )

    assert decision.primary_agent is None
    assert decision.provider_status == "timeout"


def test_semantic_router_domain_vector_timeout_abstains() -> None:
    router = SemanticAgentRouter(
        embedding_model=_HangingEmbedding(),  # type: ignore[arg-type]
        specs=PANTHEON_SPECS,
        config=SemanticRouterConfig(embedding_timeout_seconds=0.001),
    )

    decision = asyncio.run(
        router.route(
            "ambiguous question",
            t0=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            max_contributors=2,
        )
    )

    assert decision.primary_agent is None
    assert decision.provider_status == "timeout"


def test_responder_normalization_rejects_non_json_native_facts() -> None:
    normalized, error = normalize_responder_answer(
        "Njord",
        {"primary_agent": "Njord", "answer": "cost", "facts": {"scopes": {"scope-1"}}},
    )

    assert normalized is None
    assert error == "non_serializable_output"


def test_responder_normalization_rejects_non_finite_numbers() -> None:
    normalized, error = normalize_responder_answer(
        "Njord",
        {"primary_agent": "Njord", "answer": "cost", "facts": {"amount": float("nan")}},
    )

    assert normalized is None
    assert error == "non_serializable_output"


def test_agent_state_evidence_ref_rejects_process_specific_repr() -> None:
    with pytest.raises(TypeError):
        agent_state_evidence_ref("Njord", {"bad": object()})


def test_turn_payload_rejects_non_json_answer_digest_material() -> None:
    turn = Turn(
        turn_index=0,
        question="cost status",
        primary_agent="Njord",
        answer={"answer": "cost", "facts": {"bad": object()}},
        decision=RoutingDecision(primary_agent="Njord", scores={"Njord": 1.0}, tie_break="score"),
    )

    with pytest.raises(TypeError):
        turn_event_payload(session_id="session", turn=turn, contributor_limit=2)


def test_diagnostics_marks_non_json_manifest_unavailable() -> None:
    answer: dict[str, Any] = {"answer": "cost", "facts": {"bad": object()}}

    attach_pantheon_diagnostics(
        answer=answer,
        decision=RoutingDecision(primary_agent="Njord", scores={"Njord": 1.0}, tie_break="score"),
        question="cost status",
        session_id="session",
    )

    assert answer["pantheon_trace_fragment"]["evidence_manifest_status"] == "manifest_unavailable"


def test_conversation_situation_rejects_forged_requester_and_handoff_owner() -> None:
    with pytest.raises(ValueError, match="known pantheon"):
        ConversationSituation(audience="peer", requester="Mallory")
    with pytest.raises(ValueError, match="known pantheon"):
        ConversationSituation(handoff_owner="Mallory")


def test_registered_tool_answer_without_tool_evidence_abstains() -> None:
    bragi = Bragi(semantic_judgment=semantic_test_boundary())

    async def tool_answer(_agent: str, _question: str, _session: str) -> dict[str, Any]:
        return {"primary_agent": "Njord", "answer": "ok", "facts": {}}

    bragi.register_tool_answer(tool_answer)
    turn = asyncio.run(
        bragi.ask(session_id="tool-no-evidence", user_id="operator", question="cost status")
    )

    assert turn.primary_agent == "Njord"
    assert turn.answer["answer"] is None
    assert turn.answer["abstain_reason"] == "tool_evidence_incomplete"


def test_deliberation_rejects_unallowlisted_claim_evidence_ref() -> None:
    claim = _claim(
        "Njord",
        {
            "answer": "cost",
            "facts": {"evidence_refs": ["not-a-ref"]},
            "prompt_composition": {"prompt_sha256": "a" * 64},
        },
    )

    assert claim is None


def test_tool_evidence_refs_do_not_include_undeclared_id_facts() -> None:
    runtime = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="fdai.events")
    njord = runtime.agents["Njord"]

    async def broad_facts(
        _self: object, _question: str, _context: dict[str, Any]
    ) -> IntrospectionResult:
        return IntrospectionResult(
            answer="One cost scope is tracked.",
            facts={"tracked_scopes": ["scope-1"], "correlation_id": "corr-1"},
        )

    njord.introspect = MethodType(broad_facts, njord)  # type: ignore[method-assign]
    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )

    assert result.status is AgentToolStatus.OK
    assert result.evidence_refs == (agent_state_evidence_ref("Njord", dict(result.facts)),)
    assert all(not ref.startswith("correlation_id:") for ref in result.evidence_refs)


def test_boolean_only_no_data_tool_scope_abstains() -> None:
    runtime = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="fdai.events")
    njord = runtime.agents["Njord"]

    async def no_data(
        _self: object, _question: str, _context: dict[str, Any]
    ) -> IntrospectionResult:
        return IntrospectionResult(answer="No samples.", facts={"tracked_scopes": False})

    njord.introspect = MethodType(no_data, njord)  # type: ignore[method-assign]
    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )

    assert result.status is AgentToolStatus.ABSTAIN
    assert result.reason == "no_tool_data"
