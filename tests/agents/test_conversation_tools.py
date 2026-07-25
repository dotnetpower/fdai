"""Registered read-only tool parity for all fixed Pantheon agents."""

from __future__ import annotations

import asyncio
from types import MethodType

from fdai.agents import AgentToolStatus
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


def _runtime(*, disabled: frozenset[str] = frozenset(), timeout: float = 5.0) -> PantheonRuntime:
    return PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        disabled_agents=disabled,
        conversation_tool_timeout_seconds=timeout,
    )


def test_every_declared_agent_tool_is_registered_and_callable() -> None:
    runtime = _runtime()

    for spec in PANTHEON_SPECS:
        for tool_id in spec.conversation.tools:
            result = asyncio.run(
                runtime.invoke_conversation_tool(
                    agent_name=spec.name,
                    tool_id=tool_id,
                    question=f"{spec.name} {spec.question_domains[0]}",
                    trace_ref="trace-all-tools",
                )
            )
            assert result.agent == spec.name
            assert result.tool_id == tool_id
            assert result.status in {AgentToolStatus.OK, AgentToolStatus.ABSTAIN}
            assert result.prompt_sha256
            assert result.allowed_tools == spec.conversation.tools

    health = runtime.health()["conversation_tools"]
    assert health["registered"] == 30
    assert health["available"] == 30
    assert health["disabled"] == 0


def test_unknown_wrong_owner_and_disabled_tools_abstain() -> None:
    runtime = _runtime(disabled=frozenset({"Njord"}))

    unknown = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Thor",
            tool_id="read_unknown",
            question="status",
        )
    )
    wrong = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Thor",
            tool_id="read_cost_samples",
            question="cost",
        )
    )
    disabled = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost",
        )
    )

    assert unknown.reason == "unknown_tool"
    assert wrong.reason == "wrong_owner"
    assert disabled.reason == "agent_disabled"
    health = runtime.health()["conversation_tools"]
    assert health["disabled"] == 2


def test_tool_timeout_and_exception_become_abstentions() -> None:
    runtime = _runtime(timeout=0.001)
    njord = runtime.agents["Njord"]

    async def slow(_self, _question, _context):  # type: ignore[no-untyped-def]
        await asyncio.sleep(60)
        return {}

    njord.on_conversation_turn = MethodType(slow, njord)  # type: ignore[method-assign]
    timeout = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost",
        )
    )
    assert timeout.reason == "timeout"

    async def fail(_self, _question, _context):  # type: ignore[no-untyped-def]
        raise ValueError("private provider detail")

    njord.on_conversation_turn = MethodType(fail, njord)  # type: ignore[method-assign]
    failed = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost",
        )
    )
    assert failed.reason == "error"


def test_sensitive_output_is_held_without_value_leak() -> None:
    runtime = _runtime()
    saga = runtime.agents["Saga"]

    async def sensitive(_self, _question, context):  # type: ignore[no-untyped-def]
        return {
            "answer": "password=supersecretvalue",
            "facts": {"owner": "user@example.com"},
            "trace_ref": context["trace_ref"],
            "abstain_reason": None,
        }

    saga.on_conversation_turn = MethodType(sensitive, saga)  # type: ignore[method-assign]
    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Saga",
            tool_id="read_audit_chain",
            question="audit",
            trace_ref="trace-sensitive",
        )
    )

    assert result.status is AgentToolStatus.ABSTAIN
    assert result.reason == "sensitive_output"
    assert result.answer is None
    assert result.facts == {}
    assert "supersecretvalue" not in repr(result)
    assert set(result.sensitivity_labels) == {
        "pii:email",
        "secret:credential-assignment",
    }


def test_tool_result_preserves_evidence_trace_and_policy() -> None:
    runtime = _runtime()
    heimdall = runtime.agents["Heimdall"]

    async def grounded(_self, _question, context):  # type: ignore[no-untyped-def]
        return {
            "answer": "One fresh observation is available.",
            "facts": {
                "evidence_refs": ["audit:one", "metric:two"],
                "snapshot_ref": "snapshot-three",
            },
            "trace_ref": context["trace_ref"],
            "abstain_reason": None,
        }

    heimdall.on_conversation_turn = MethodType(grounded, heimdall)  # type: ignore[method-assign]
    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Heimdall",
            tool_id="read_observations",
            question="observations",
            trace_ref="trace-grounded",
        )
    )

    assert result.status is AgentToolStatus.OK
    assert result.trace_ref == "trace-grounded"
    assert result.evidence_refs == (
        "audit:one",
        "metric:two",
        "snapshot_ref:snapshot-three",
    )
    assert len(result.prompt_sha256) == 64
    assert result.allowed_tools == heimdall.spec.conversation.tools
    counters = runtime.health()["conversation_tools"]["by_agent"]["Heimdall"]["counters"]
    assert counters["conversation_tool:read_observations:ok"] == 1


def test_tool_inputs_and_outputs_are_bounded() -> None:
    runtime = _runtime()
    saga = runtime.agents["Saga"]

    too_long = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Saga",
            tool_id="read_audit_chain",
            question="x" * 2_001,
        )
    )
    bad_trace = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Saga",
            tool_id="read_audit_chain",
            question="audit",
            trace_ref="password=supersecretvalue",
        )
    )

    async def oversized(_self, _question, context):  # type: ignore[no-untyped-def]
        return {
            "answer": "x" * 65_536,
            "facts": {},
            "trace_ref": context["trace_ref"],
            "abstain_reason": None,
        }

    saga.on_conversation_turn = MethodType(oversized, saga)  # type: ignore[method-assign]
    output = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Saga",
            tool_id="read_audit_chain",
            question="audit",
        )
    )

    assert too_long.reason == "question_too_long"
    assert bad_trace.reason == "invalid_trace_ref"
    assert bad_trace.trace_ref == ""
    assert output.reason == "output_too_large"
