"""Prompt quality and bounded conversational-deliberation contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

import pytest

from fdai.agents._framework.charters import conversation_prompt_layers
from fdai.agents._framework.deliberation import (
    DeliberationRequest,
    T2ConversationSynthesizer,
)
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.semantic_routing import SemanticRouterConfig
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

PromptCheck = tuple[str, Callable[[str], bool]]

_CRITIQUE_ROUNDS: tuple[tuple[str, tuple[PromptCheck, ...]], ...] = (
    (
        "identity",
        (
            ("canonical identity", lambda prompt: prompt.startswith("you are ")),
            ("fixed pantheon", lambda prompt: "fixed operational agents" in prompt),
        ),
    ),
    (
        "mandate",
        (
            ("positive mandate", lambda prompt: "mandate:" in prompt),
            ("owned scope", lambda prompt: "owned state" in prompt),
        ),
    ),
    (
        "authority",
        (
            ("role boundary", lambda prompt: "authority boundary:" in prompt),
            ("typed authority", lambda prompt: "typed pipeline remains authoritative" in prompt),
            ("read-only port", lambda prompt: "read-only" in prompt),
        ),
    ),
    (
        "grounding",
        (
            ("allowed tools", lambda prompt: "allowed tools" in prompt),
            ("evidence refs", lambda prompt: "evidence refs" in prompt),
            ("fact inference split", lambda prompt: "facts, inferences, and unknowns" in prompt),
        ),
    ),
    (
        "epistemics",
        (
            ("insufficient evidence", lambda prompt: "insufficient" in prompt),
            ("counterevidence", lambda prompt: "counterevidence" in prompt),
            ("calibrated uncertainty", lambda prompt: "uncertainty" in prompt),
        ),
    ),
    (
        "human_dialogue",
        (
            ("operator locale", lambda prompt: "operator's locale" in prompt),
            ("minimal clarification", lambda prompt: "minimum missing scope" in prompt),
        ),
    ),
    (
        "peer_protocol",
        (
            ("peer discussion", lambda prompt: "peer discussion" in prompt),
            ("requester attribution", lambda prompt: "requester" in prompt),
            ("correlation trace", lambda prompt: "correlation trace" in prompt),
        ),
    ),
    (
        "disagreement",
        (
            ("claim challenge", lambda prompt: "challenge peer claims" in prompt),
            ("no conflict averaging", lambda prompt: "never average conflicts" in prompt),
        ),
    ),
    (
        "tiers",
        (
            ("T1 selection", lambda prompt: "t1" in prompt),
            ("T2 synthesis", lambda prompt: "t2" in prompt),
        ),
    ),
    (
        "security_output",
        (
            ("untrusted content", lambda prompt: 'trusted="false"' in prompt),
            ("sensitive output", lambda prompt: "sensitive values" in prompt),
            ("bounded conclusion", lambda prompt: "bounded conclusion" in prompt),
        ),
    ),
)


def test_each_agent_prompt_passes_twenty_four_checks_across_ten_rounds() -> None:
    assert len(_CRITIQUE_ROUNDS) == 10
    assert sum(len(checks) for _, checks in _CRITIQUE_ROUNDS) >= 24

    failures: list[str] = []
    for spec in PANTHEON_SPECS:
        prompt = spec.conversation.system_prompt.casefold()
        for round_name, checks in _CRITIQUE_ROUNDS:
            for check_name, check in checks:
                if not check(prompt):
                    failures.append(f"{spec.name}:{round_name}:{check_name}")

    assert failures == []


def test_each_agent_improves_monotonically_over_ten_critique_rounds() -> None:
    for spec in PANTHEON_SPECS:
        mandate = spec.conversation.system_prompt.splitlines()[1].removeprefix("Mandate: ")
        layers = conversation_prompt_layers(spec.name, mandate)
        assert len(layers) == 10

        scores: list[int] = []
        for round_index in range(1, 11):
            snapshot = "\n".join(layers[:round_index]).casefold()
            results = [check(snapshot) for _, checks in _CRITIQUE_ROUNDS for _, check in checks]
            assert len(results) >= 24
            scores.append(sum(results))

        assert all(after > before for before, after in zip(scores, scores[1:], strict=False))
        assert scores[-1] == sum(len(checks) for _, checks in _CRITIQUE_ROUNDS)


class _CrossDomainEmbedding:
    dim = len(PANTHEON_SPECS)

    async def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * self.dim
        for index, spec in enumerate(PANTHEON_SPECS):
            if text.startswith(f"{spec.name}\n"):
                vector[index] = 1.0
                return vector
        vector[_agent_index("Njord")] = 1.0
        vector[_agent_index("Freyr")] = 0.8
        return vector


class _T2Synthesizer:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def synthesize(self, request: DeliberationRequest) -> str:
        self.requests.append(request)
        return "Capacity evidence outweighs the bounded cost objection; disagreement remains."


class _T2FailureSynthesizer:
    def __init__(self, outcome: str | None | Exception) -> None:
        self.outcome = outcome

    async def synthesize(self, request: DeliberationRequest) -> str | None:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _runtime(*, t2: T2ConversationSynthesizer | None = None) -> PantheonRuntime:
    return PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=_CrossDomainEmbedding(),
        semantic_router_config=SemanticRouterConfig(
            cosine_threshold=0.6,
            margin_threshold=0.08,
        ),
        conversation_t2_synthesizer=t2,
    )


def _agent_index(name: str) -> int:
    return next(index for index, spec in enumerate(PANTHEON_SPECS) if spec.name == name)


def test_deliberation_requires_t1_instead_of_falling_back_to_t0() -> None:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )

    result = asyncio.run(
        runtime.deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-no-t1",
        )
    )

    assert result["status"] == "abstain"
    assert result["reason"] == "t1_unavailable"
    assert result["rounds"] == []


def test_t1_deliberation_collects_position_and_peer_critique() -> None:
    result = asyncio.run(
        _runtime().deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-t1",
        )
    )

    assert result["status"] == "completed"
    assert result["tier"] == "T1"
    assert result["primary_agent"] == "Njord"
    assert result["participants"] == ["Njord", "Freyr"]
    assert [round_["phase"] for round_ in result["rounds"]] == ["position", "critique"]
    assert result["rounds"][0]["contributions"][0]["agent"] == "Njord"
    assert result["rounds"][1]["contributions"][0]["agent"] == "Freyr"
    assert result["trace_ref"] == "corr-t1"
    assert result["authority"] == "presentation_only"


def test_t2_deliberation_synthesizes_without_raising_authority() -> None:
    synthesizer = _T2Synthesizer()
    result = asyncio.run(
        _runtime(t2=synthesizer).deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-t2",
        )
    )

    assert result["status"] == "completed"
    assert result["tier"] == "T2"
    assert result["authority"] == "presentation_only"
    assert result["conclusion"].endswith("disagreement remains.")
    assert len(synthesizer.requests) == 1
    request = synthesizer.requests[0]
    assert isinstance(request, DeliberationRequest)
    assert len(request.participant_prompts) == 2
    assert all("Authority boundary:" in prompt for _, prompt in request.participant_prompts)
    assert "Authority boundary:" not in str(result)


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    (
        (None, "abstained"),
        (RuntimeError("provider unavailable"), "error"),
        ("x" * 4_001, "output_too_large"),
        ("password=supersecretvalue", "sensitive_output"),
    ),
)
def test_t2_failure_preserves_t1_discussion(
    outcome: str | None | Exception,
    expected_status: str,
) -> None:
    result = asyncio.run(
        _runtime(t2=_T2FailureSynthesizer(outcome)).deliberate(
            question="Compare cost and capacity evidence.",
            requester="Forseti",
            correlation_id="corr-t2-failure",
        )
    )

    assert result["status"] == "completed"
    assert result["tier"] == "T1"
    assert result["t2_status"] == expected_status
    assert result["authority"] == "presentation_only"
    assert len(result["rounds"]) == 2


def test_deliberation_action_intent_requires_typed_pipeline() -> None:
    result = asyncio.run(
        _runtime().deliberate(
            question="scale down vm-1 now",
            requester="Forseti",
            correlation_id="corr-action",
        )
    )

    assert result["status"] == "abstain"
    assert result["reason"] == "requires_typed_pipeline"
    assert result["requires_typed_pipeline"] is True
