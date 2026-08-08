"""T1 semantic fallback routing over frozen multilingual agent charters."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.semantic_routing import SemanticRouterConfig
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_NAMES = tuple(spec.name for spec in PANTHEON_SPECS)


class KeywordEmbedding:
    dim = len(_NAMES)

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.raise_on_query = False

    async def embed(self, text: str) -> Sequence[float]:
        self.calls.append(text)
        vector = [0.0] * self.dim
        for index, name in enumerate(_NAMES):
            if text.startswith(f"{name}\n"):
                vector[index] = 1.0
                return vector
        if self.raise_on_query:
            raise RuntimeError("embedding unavailable")
        lowered = text.casefold()
        if "지출" in text or "비용" in text or "spend" in lowered:
            vector[_NAMES.index("Njord")] = 1.0
        elif "모호한 관측" in text:
            vector[_NAMES.index("Heimdall")] = 1.0
            vector[_NAMES.index("Huginn")] = 1.0
        elif "복구" in text:
            vector[_NAMES.index("Vidar")] = 1.0
        else:
            vector[_NAMES.index("Bragi")] = 1.0
        return vector


def _runtime(model: KeywordEmbedding, *, margin: float = 0.08) -> PantheonRuntime:
    return PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        conversation_embedding_model=model,
        semantic_router_config=SemanticRouterConfig(
            cosine_threshold=0.6,
            margin_threshold=margin,
        ),
    )


def test_explicit_and_t0_routes_skip_agent_embedding_but_select_owner_tools() -> None:
    model = KeywordEmbedding()
    runtime = _runtime(model)

    explicit = asyncio.run(
        runtime.ask(session_id="explicit", user_id="operator", question="Thor action status")
    )
    t0 = asyncio.run(runtime.ask(session_id="t0", user_id="operator", question="budget status"))

    assert explicit is not None and explicit.primary_agent == "Thor"
    assert t0 is not None and t0.primary_agent == "Njord"
    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)
    # One tool catalog plus one tool query per turn. The agent-domain
    # router is still skipped for explicit and T0 routes.
    assert len(model.calls) == tools + 2
    assert not any(text.startswith(f"{name}\n") for text in model.calls for name in _NAMES)


def test_korean_t1_query_routes_to_cost_agent_and_caches_domains() -> None:
    model = KeywordEmbedding()
    runtime = _runtime(model)

    first = asyncio.run(
        runtime.ask(
            session_id="semantic-one",
            user_id="operator",
            question="이번 달 클라우드 지출이 왜 늘었는지 알려줘",
        )
    )
    first_call_count = len(model.calls)
    second = asyncio.run(
        runtime.ask(
            session_id="semantic-two",
            user_id="operator",
            question="서비스 비용 추세를 보여줘",
        )
    )

    assert first is not None and first.primary_agent == "Njord"
    assert first.answer["routing_method"] == "t1_semantic"
    assert first.answer["semantic_score"] == 1.0
    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)
    # Agent-domain catalog + route query + tool catalog + tool query.
    assert first_call_count == len(PANTHEON_SPECS) + tools + 2
    assert second is not None and second.primary_agent == "Njord"
    # Both catalogs are cached; only the route and tool queries remain.
    assert len(model.calls) == first_call_count + 2


def test_low_semantic_margin_abstains_instead_of_guessing() -> None:
    model = KeywordEmbedding()
    runtime = _runtime(model, margin=0.1)

    turn = asyncio.run(
        runtime.ask(
            session_id="semantic-tie",
            user_id="operator",
            question="모호한 관측 상태를 설명해줘",
        )
    )

    assert turn is not None
    assert turn.primary_agent is None
    assert turn.answer["handoff_needed"] is True


def test_embedding_error_preserves_abstention() -> None:
    model = KeywordEmbedding()
    model.raise_on_query = True
    runtime = _runtime(model)

    turn = asyncio.run(
        runtime.ask(
            session_id="semantic-error",
            user_id="operator",
            question="아무 도메인에도 없는 질문",
        )
    )

    assert turn is not None
    assert turn.primary_agent is None
    assert turn.answer["handoff_needed"] is True


def test_action_intent_never_calls_semantic_router() -> None:
    model = KeywordEmbedding()
    runtime = _runtime(model)

    turn = asyncio.run(
        runtime.ask(
            session_id="semantic-action",
            user_id="operator",
            question="restart vm-1 now",
        )
    )

    assert turn is not None
    assert turn.answer["requires_typed_pipeline"] is True
    assert model.calls == []


def test_every_charter_has_multilingual_routing_examples() -> None:
    for spec in PANTHEON_SPECS:
        examples = spec.conversation.routing_examples
        assert len(examples) >= 2
        assert any(any("가" <= character <= "힣" for character in item) for item in examples)
