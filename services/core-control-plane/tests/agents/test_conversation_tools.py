"""Registered read-only tool parity for all fixed Pantheon agents."""

from __future__ import annotations

import asyncio
from types import MethodType

import pytest
from fdai.agents import AgentToolStatus
from fdai.agents._framework.bragi_contributors import normalize_responder_answer
from fdai.agents._framework.introspection import IntrospectionResult
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
        expected_policy = spec.conversation_policy()
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
            assert result.charter_version == spec.conversation.version
            assert result.charter_sha256 == expected_policy["charter_sha256"]
            assert result.prompt_sha256 == expected_policy["prompt_sha256"]
            assert result.allowed_tools == spec.conversation.tools
            assert result.evidence_refs
            assert all(not ref.startswith("agent-spec:") for ref in result.evidence_refs)

    health = runtime.health()["conversation_tools"]
    declared_tool_count = sum(len(spec.conversation.tools) for spec in PANTHEON_SPECS)
    assert health["registered"] == declared_tool_count
    assert health["available"] == declared_tool_count
    assert health["disabled"] == 0


def test_all_charter_digests_are_deterministic_and_unique() -> None:
    first = {spec.name: spec.conversation_policy() for spec in PANTHEON_SPECS}
    replay = {spec.name: spec.conversation_policy() for spec in PANTHEON_SPECS}

    assert first == replay
    assert len({policy["charter_sha256"] for policy in first.values()}) == len(PANTHEON_SPECS)
    assert len({policy["prompt_sha256"] for policy in first.values()}) == len(PANTHEON_SPECS)


@pytest.mark.parametrize(
    "value",
    (True, 0.0, -1.0, float("nan"), float("inf"), 10**4_000),
)
def test_tool_timeout_must_be_a_positive_finite_number(value: float) -> None:
    with pytest.raises(ValueError):
        _runtime(timeout=value)


def test_content_addressed_digest_is_not_misclassified_as_card_number() -> None:
    digest = "4111111111111111" + "a" * 48

    normalized, error = normalize_responder_answer(
        "Bragi",
        {
            "primary_agent": "Bragi",
            "answer": "One grounded capability record is available.",
            "facts": {"evidence_refs": [f"agent-state:Bragi:sha256:{digest}"]},
            "conversation_policy": {"prompt_sha256": digest},
        },
    )

    assert error is None
    assert normalized is not None
    assert normalized["facts"]["evidence_refs"] == [f"agent-state:Bragi:sha256:{digest}"]


@pytest.mark.parametrize(
    "payload",
    (
        {
            "answer": "I will restart it.",
            "abstain_reason": "requires_typed_pipeline",
            "requires_typed_pipeline": True,
        },
        {
            "answer": None,
            "abstain_reason": "no_route",
            "requires_typed_pipeline": True,
        },
    ),
)
def test_responder_cannot_mix_an_answer_with_typed_pipeline_authority(
    payload: dict[str, object],
) -> None:
    normalized, error = normalize_responder_answer(
        "Bragi",
        {"primary_agent": "Bragi", "facts": {}, **payload},
    )

    assert normalized is None
    assert error == "typed_pipeline_conflict"


def test_each_agent_tool_projects_a_distinct_owned_fact_scope() -> None:
    runtime = _runtime()

    for spec in PANTHEON_SPECS:
        results = [
            asyncio.run(
                runtime.invoke_conversation_tool(
                    agent_name=spec.name,
                    tool_id=tool_id,
                    question=f"{spec.name}, describe your current capability",
                )
            )
            for tool_id in spec.conversation.tools
        ]

        assert all(result.status is AgentToolStatus.OK for result in results), spec.name
        assert len({result.answer for result in results}) == len(results), spec.name
        assert len({tuple(sorted(result.facts)) for result in results}) == len(results), spec.name


def test_tool_projection_rejects_undeclared_reference_facts() -> None:
    runtime = _runtime()
    njord = runtime.agents["Njord"]

    async def broad_facts(_self, _question, _context):  # type: ignore[no-untyped-def]
        return IntrospectionResult(
            answer="One cost scope is tracked.",
            facts={
                "tracked_scopes": ["scope-1"],
                "evidence_refs": ["cost-snapshot:one"],
                "internal_runtime_ref": "internal-state",
                "unrelated_state": "not-owned-by-this-tool",
            },
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
    assert result.facts == {
        "tracked_scopes": ["scope-1"],
        "evidence_refs": ["cost-snapshot:one"],
    }


def test_agent_state_evidence_ref_is_stable_and_changes_with_owned_facts() -> None:
    from fdai.agents.njord import Njord

    runtime = _runtime()
    njord = runtime.agents["Njord"]
    assert isinstance(njord, Njord)

    first = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )
    replay = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )
    asyncio.run(njord.ingest_cost_sample(scope="scope-1", amount_usd=10.0))
    changed = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )

    assert first.evidence_refs == replay.evidence_refs
    assert first.evidence_refs != changed.evidence_refs
    assert first.evidence_refs[0].startswith("agent-state:Njord:sha256:")


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
    njord = next(spec for spec in PANTHEON_SPECS if spec.name == "Njord")
    assert health["disabled"] == len(njord.conversation.tools)


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


@pytest.mark.parametrize(
    "bad_value",
    (object(), float("nan"), float("inf"), -float("inf")),
)
def test_non_serializable_or_non_finite_output_is_held(bad_value: object) -> None:
    """Agent bugs never become process-specific evidence strings."""
    runtime = _runtime()
    njord = runtime.agents["Njord"]

    async def invalid(_question: str, _context: dict[str, object]) -> dict[str, object]:
        return {
            "answer": "invalid fact",
            "facts": {"bad": bad_value},
        }

    njord.on_conversation_turn = invalid  # type: ignore[assignment,method-assign]

    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )

    assert result.status is AgentToolStatus.ABSTAIN
    assert result.reason == "non_serializable_output"
    assert result.answer is None
    assert result.facts == {}


@pytest.mark.parametrize(
    "envelope",
    (
        None,
        {"answer": 1, "facts": {}},
        {"answer": "answer", "facts": None},
        {"answer": "answer", "facts": {}, "abstain_reason": 1},
    ),
)
def test_malformed_tool_output_is_held(envelope: object) -> None:
    runtime = _runtime()
    njord = runtime.agents["Njord"]

    async def malformed(_question: str, _context: dict[str, object]) -> object:
        return envelope

    njord.on_conversation_turn = malformed  # type: ignore[assignment,method-assign]

    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
            trace_ref="server-trace",
        )
    )

    assert result.status is AgentToolStatus.ABSTAIN
    assert result.reason == "malformed_output"
    assert result.trace_ref == "server-trace"


def test_agent_output_cannot_replace_server_owned_trace_ref() -> None:
    runtime = _runtime()
    njord = runtime.agents["Njord"]

    async def forged(_self, _question, _context):  # type: ignore[no-untyped-def]
        return {
            "answer": "One cost sample is available.",
            "facts": {},
            "trace_ref": "forged-trace",
            "abstain_reason": None,
        }

    njord.on_conversation_turn = MethodType(forged, njord)  # type: ignore[method-assign]

    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
            trace_ref="server-trace",
        )
    )

    assert result.status is AgentToolStatus.OK
    assert result.trace_ref == "server-trace"


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
    assert result.charter_version == "v3"
    assert len(result.charter_sha256) == 64
    assert result.allowed_tools == heimdall.spec.conversation.tools
    counters = runtime.health()["conversation_tools"]["by_agent"]["Heimdall"]["counters"]
    assert counters["conversation_tool:read_observations:ok"] == 1


def test_evidence_reference_cap_applies_to_explicit_and_discovered_refs() -> None:
    """Auto-discovered ``*_ref`` fields cannot bypass the global cap."""
    runtime = _runtime()
    heimdall = runtime.agents["Heimdall"]

    async def many_refs(_self, _question, context):  # type: ignore[no-untyped-def]
        facts: dict[str, object] = {
            "evidence_refs": [f"explicit:{index}" for index in range(50)],
        }
        facts.update({f"item_{index}_ref": f"ref-{index}" for index in range(100)})
        return {
            "answer": "Many observations are available.",
            "facts": facts,
            "trace_ref": context["trace_ref"],
            "abstain_reason": None,
        }

    heimdall.on_conversation_turn = MethodType(many_refs, heimdall)  # type: ignore[method-assign]

    result = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Heimdall",
            tool_id="read_observations",
            question="observations",
        )
    )

    assert result.status is AgentToolStatus.OK
    assert len(result.evidence_refs) == 20
    assert result.evidence_ref_count == 150
    assert result.evidence_refs_truncated is True


@pytest.mark.asyncio
async def test_cancellation_resistant_tool_timeout_is_bounded_and_owned() -> None:
    """A handler that suppresses cancellation cannot hold the caller forever."""
    runtime = _runtime(timeout=0.01)
    njord = runtime.agents["Njord"]
    release = asyncio.Event()

    async def resists_once(_self, _question, _context):  # type: ignore[no-untyped-def]
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"answer": "late", "facts": {}}

    njord.on_conversation_turn = MethodType(resists_once, njord)  # type: ignore[method-assign]

    result = await asyncio.wait_for(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        ),
        timeout=0.1,
    )

    assert result.reason == "timeout"
    assert runtime.health()["conversation_tools"]["in_flight"] == 1
    release.set()
    await runtime.stop()
    assert runtime.health()["conversation_tools"]["in_flight"] == 0


@pytest.mark.asyncio
async def test_stopped_tool_registry_refuses_new_invocations() -> None:
    runtime = _runtime()
    await runtime.stop()

    result = await runtime.invoke_conversation_tool(
        agent_name="Njord",
        tool_id="read_cost_samples",
        question="cost samples",
    )

    assert result.reason == "registry_stopped"


@pytest.mark.asyncio
async def test_stopped_tool_registry_still_sanitizes_trace_input() -> None:
    runtime = _runtime()
    await runtime.stop()

    result = await runtime.invoke_conversation_tool(
        agent_name="Njord",
        tool_id="read_cost_samples",
        question="cost samples",
        trace_ref="password=supersecretvalue",
    )

    assert result.reason == "invalid_trace_ref"
    assert result.trace_ref == ""


@pytest.mark.asyncio
async def test_tool_registry_caps_cancellation_resistant_in_flight_work() -> None:
    runtime = _runtime(timeout=0.001)
    njord = runtime.agents["Njord"]
    release = asyncio.Event()

    async def resists_once(_self, _question, _context):  # type: ignore[no-untyped-def]
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"answer": "late", "facts": {}}

    njord.on_conversation_turn = MethodType(resists_once, njord)  # type: ignore[method-assign]
    registry = runtime._conversation_tools
    assert registry is not None
    raw_limit = registry.snapshot()["in_flight_limit"]
    assert isinstance(raw_limit, int)
    limit = raw_limit

    timed_out = await asyncio.gather(
        *(
            runtime.invoke_conversation_tool(
                agent_name="Njord",
                tool_id="read_cost_samples",
                question=f"cost samples {index}",
            )
            for index in range(limit)
        )
    )
    saturated = await runtime.invoke_conversation_tool(
        agent_name="Njord",
        tool_id="read_cost_samples",
        question="one more cost sample",
    )

    assert {result.reason for result in timed_out} == {"timeout"}
    assert saturated.reason == "tool_capacity_exhausted"
    assert registry.snapshot()["in_flight"] == limit
    release.set()
    await runtime.stop()


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
