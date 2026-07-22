from __future__ import annotations

import pytest

from fdai.agents import Bragi, Heimdall, PantheonRuntime
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


@pytest.mark.parametrize(
    "question",
    [
        "vm-01 is stopped; who stopped it?",
        "vm-01을 누가 중지했어?",
        "Show the recent Activity Log for vm-01",
        "vm-01 최근 변경 이력을 보여줘",
        "Was vm-01 affected by a platform health event?",
        "vm-01에 플랫폼 장애가 있었어?",
        "Find an OS shutdown in the guest event log for vm-01",
        "vm-01의 게스트 운영체제 종료 이벤트를 찾아줘",
        "What is the current state of vm-01?",
        "vm-01의 현재 상태는?",
    ],
)
def test_bragi_routes_bilingual_read_investigations_to_heimdall(question: str) -> None:
    decision = Bragi().route(question)
    assert decision.primary_agent == "Heimdall"
    assert decision.tie_break is not None
    assert decision.tie_break.startswith("read_investigation:")
    assert decision.contributors == ()


def test_explicit_agent_still_precedes_read_investigation_routing() -> None:
    decision = Bragi().route("Saga, who stopped vm-01?")
    assert decision.primary_agent == "Saga"
    assert decision.tie_break == "explicit_agent"


async def test_bragi_routes_to_composed_heimdall_read_responder() -> None:
    contexts: list[dict[str, object]] = []

    async def investigate(
        question: str,
        context: dict[str, object],
    ) -> dict[str, object] | None:
        contexts.append(context)
        return {
            "answer": f"Investigated: {question}",
            "facts": {"status": "matched", "evidence_refs": ("evidence:one",)},
        }

    bragi = Bragi()
    heimdall = Heimdall(read_investigation_hook=investigate)
    bragi.register_responder("Heimdall", heimdall.on_conversation_turn)

    turn = await bragi.ask(
        session_id="session-one",
        user_id="principal-one",
        question="Who stopped vm-01?",
    )

    assert turn.primary_agent == "Heimdall"
    assert turn.answer["answer"] == "Investigated: Who stopped vm-01?"
    assert turn.answer["facts"]["status"] == "matched"
    assert contexts == [{"session_id": "session-one", "user_id": "principal-one"}]


async def test_runtime_read_investigation_never_publishes_event_or_invokes_thor() -> None:
    provider = InMemoryEventBus()
    executor_calls: list[dict[str, object]] = []

    async def execute(context: dict[str, object]) -> bool:
        executor_calls.append(context)
        return True

    async def investigate(
        _question: str,
        _context: dict[str, object],
    ) -> dict[str, object] | None:
        return {
            "answer": "Bounded read completed.",
            "facts": {"status": "matched", "evidence_refs": ("evidence:one",)},
        }

    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic="fdai.events",
        read_investigation_hook=investigate,
        thor_executor=execute,
    )
    turn = await runtime.ask(
        session_id="session-one",
        user_id="principal-one",
        question="Who stopped vm-01?",
        allow_action_proposal=False,
        materialize_handoff=False,
    )

    assert turn is not None
    assert turn.primary_agent == "Heimdall"
    assert turn.answer["facts"]["status"] == "matched"
    assert executor_calls == []
    assert [item async for item in provider.subscribe("fdai.events", "inspect-raw")] == []
    assert [item async for item in provider.subscribe("object.event", "inspect-normalized")] == []
