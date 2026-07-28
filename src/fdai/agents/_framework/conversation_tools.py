"""Registered read-only tool surface for fixed Pantheon agent charters."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final

from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import agent_state_evidence_ref
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

_MAX_QUESTION_CHARS = 2_000
_MAX_TRACE_REF_CHARS = 256
_MAX_OUTPUT_BYTES = 65_536
_MAX_EVIDENCE_REFS = 20
_MAX_IN_FLIGHT = 16
_SHUTDOWN_TIMEOUT_SECONDS = 1.0

#: The tool this task is already running, if any.
#:
#: Tool dispatch is one level deep by construction: an :class:`Agent` holds
#: no reference to this registry, so there is no edge from an agent turn
#: back to a tool call. This variable is the second lock. If a future edit
#: ever creates that edge, the nested call is refused here rather than
#: recursing, because a conversational port that can call itself can hang
#: the whole read path. ``ContextVar`` is per-task, so tools dispatched
#: concurrently each see their own empty value and only a genuinely nested
#: call sees a non-empty one.
_TOOL_IN_FLIGHT: Final[ContextVar[str]] = ContextVar("fdai_conversation_tool_in_flight", default="")


class AgentToolStatus(StrEnum):
    OK = "ok"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class AgentToolResult:
    agent: str
    tool_id: str
    status: AgentToolStatus
    answer: str | None
    facts: Mapping[str, Any]
    evidence_refs: tuple[str, ...]
    reason: str | None
    trace_ref: str
    charter_version: str
    charter_sha256: str
    prompt_sha256: str
    allowed_tools: tuple[str, ...]
    evidence_ref_count: int = 0
    evidence_refs_truncated: bool = False
    sensitivity_labels: tuple[str, ...] = ()


class AgentConversationToolRegistry:
    """Map each declared tool id to its owning agent's guarded read-only port."""

    def __init__(
        self,
        *,
        agents: Mapping[str, Agent],
        disabled_agents: frozenset[str],
        timeout_seconds: float = 5.0,
    ) -> None:
        if not _is_finite_number(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("agent conversation tool timeout MUST be positive")
        self._agents = dict(agents)
        self._disabled = disabled_agents
        self._timeout_seconds = timeout_seconds
        self._owners: dict[str, str] = {}
        self._tasks: set[asyncio.Task[Mapping[str, Any]]] = set()
        self._stopped = False
        for spec in PANTHEON_SPECS:
            for tool_id in spec.conversation.tools:
                prior = self._owners.setdefault(tool_id, spec.name)
                if prior != spec.name:
                    raise ValueError(f"conversation tool owner conflict: {tool_id}")

    async def invoke(
        self,
        *,
        agent_name: str,
        tool_id: str,
        question: str,
        trace_ref: str = "",
    ) -> AgentToolResult:
        if len(question) > _MAX_QUESTION_CHARS:
            return self._abstain(agent_name, tool_id, "question_too_long", "")
        if len(trace_ref) > _MAX_TRACE_REF_CHARS or scan_text(trace_ref):
            return self._abstain(agent_name, tool_id, "invalid_trace_ref", "")
        if self._stopped:
            return self._abstain(agent_name, tool_id, "registry_stopped", trace_ref)
        owner = self._owners.get(tool_id)
        if owner is None:
            return self._abstain(agent_name, tool_id, "unknown_tool", trace_ref)
        if owner != agent_name:
            return self._abstain(agent_name, tool_id, "wrong_owner", trace_ref)
        if agent_name in self._disabled or agent_name not in self._agents:
            return self._abstain(agent_name, tool_id, "agent_disabled", trace_ref)
        in_flight = _TOOL_IN_FLIGHT.get()
        if in_flight:
            # Depth is capped at one. Refusing is not a degradation here:
            # a nested dispatch means a wiring bug, and answering it would
            # trade an honest abstain for an unbounded call chain.
            return self._abstain(agent_name, tool_id, f"reentrant_tool_call:{in_flight}", trace_ref)
        if len(self._tasks) >= _MAX_IN_FLIGHT:
            return self._abstain(agent_name, tool_id, "tool_capacity_exhausted", trace_ref)
        agent = self._agents[agent_name]
        task = asyncio.create_task(
            self._invoke_agent(agent, tool_id, question, trace_ref),
            name=f"conversation-tool:{agent_name}:{tool_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        try:
            done, _pending = await asyncio.wait((task,), timeout=self._timeout_seconds)
        except asyncio.CancelledError:
            task.cancel()
            raise
        if not done:
            task.cancel()
            agent.record_behavior(f"conversation_tool:{tool_id}:timeout")
            return self._abstain(agent_name, tool_id, "timeout", trace_ref)
        try:
            envelope = task.result()
        except asyncio.CancelledError:
            raise
        except Exception:
            agent.record_behavior(f"conversation_tool:{tool_id}:error")
            return self._abstain(agent_name, tool_id, "error", trace_ref)

        if not isinstance(envelope, Mapping):
            agent.record_behavior(f"conversation_tool:{tool_id}:malformed")
            return self._abstain(agent_name, tool_id, "malformed_output", trace_ref)
        answer = envelope.get("answer")
        facts = envelope.get("facts")
        abstain_reason = envelope.get("abstain_reason")
        if (
            (answer is not None and not isinstance(answer, str))
            or not isinstance(facts, Mapping)
            or (abstain_reason is not None and not isinstance(abstain_reason, str))
        ):
            agent.record_behavior(f"conversation_tool:{tool_id}:malformed")
            return self._abstain(agent_name, tool_id, "malformed_output", trace_ref)
        safe_answer = answer
        safe_facts = dict(facts)
        try:
            serialized = json.dumps(
                {"answer": safe_answer, "facts": safe_facts, "trace_ref": trace_ref},
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            # ``default=str`` would turn a buggy object into a
            # process-specific repr (often including a memory address)
            # and present it as replayable evidence. Hold the result
            # instead of hiding the agent contract violation.
            agent.record_behavior(f"conversation_tool:{tool_id}:non_serializable")
            return self._abstain(agent_name, tool_id, "non_serializable_output", trace_ref)
        if len(serialized.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            agent.record_behavior(f"conversation_tool:{tool_id}:oversize")
            return self._abstain(agent_name, tool_id, "output_too_large", trace_ref)
        normalized = json.loads(serialized)
        safe_answer = normalized["answer"]
        safe_facts = normalized["facts"]
        result_trace_ref = normalized["trace_ref"]
        findings = scan_text(serialized)
        if findings:
            agent.record_behavior(f"conversation_tool:{tool_id}:sensitive")
            labels = tuple(sorted({f"{item.kind.value}:{item.label}" for item in findings}))
            result = self._abstain(agent_name, tool_id, "sensitive_output", trace_ref)
            return replace(result, sensitivity_labels=labels)
        if safe_answer is None or isinstance(abstain_reason, str):
            agent.record_behavior(f"conversation_tool:{tool_id}:abstain")
            return self._abstain(
                agent_name,
                tool_id,
                str(abstain_reason or "no_answer"),
                trace_ref,
            )
        agent.record_behavior(f"conversation_tool:{tool_id}:ok")
        charter_version, charter_sha256, prompt_sha256 = _policy_attribution(agent)
        evidence_refs, evidence_ref_count = _evidence_refs(safe_facts, agent_name=agent_name)
        return AgentToolResult(
            agent=agent_name,
            tool_id=tool_id,
            status=AgentToolStatus.OK,
            answer=safe_answer,
            facts=safe_facts,
            evidence_refs=evidence_refs,
            reason=None,
            trace_ref=result_trace_ref,
            charter_version=charter_version,
            charter_sha256=charter_sha256,
            prompt_sha256=prompt_sha256,
            allowed_tools=agent.spec.conversation.tools,
            evidence_ref_count=evidence_ref_count,
            evidence_refs_truncated=evidence_ref_count > len(evidence_refs),
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "registered": len(self._owners),
            "available": sum(owner in self._agents for owner in self._owners.values()),
            "disabled": sum(owner not in self._agents for owner in self._owners.values()),
            "in_flight": len(self._tasks),
            "in_flight_limit": _MAX_IN_FLIGHT,
            "stopped": self._stopped,
            "by_agent": {
                spec.name: {
                    "available": spec.name in self._agents,
                    "tools": list(spec.conversation.tools),
                    "counters": {
                        key: count
                        for key, count in self._agents[spec.name].behavior_snapshot().items()
                        if key.startswith("conversation_tool:")
                    }
                    if spec.name in self._agents
                    else {},
                }
                for spec in PANTHEON_SPECS
            },
        }

    async def stop(self) -> None:
        """Refuse new work and boundedly cancel registry-owned invocations."""
        self._stopped = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=_SHUTDOWN_TIMEOUT_SECONDS)

    @staticmethod
    async def _invoke_agent(
        agent: Agent,
        tool_id: str,
        question: str,
        trace_ref: str,
    ) -> Mapping[str, Any]:
        token = _TOOL_IN_FLIGHT.set(tool_id)
        try:
            return await agent.on_conversation_turn(
                question,
                {"trace_ref": trace_ref, "conversation_tool": tool_id},
            )
        finally:
            _TOOL_IN_FLIGHT.reset(token)

    def _task_done(self, task: asyncio.Task[Mapping[str, Any]]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _abstain(
        self,
        agent_name: str,
        tool_id: str,
        reason: str,
        trace_ref: str,
    ) -> AgentToolResult:
        agent = self._agents.get(agent_name)
        charter_version, charter_sha256, prompt_sha256 = (
            _policy_attribution(agent) if agent is not None else ("", "", "")
        )
        return AgentToolResult(
            agent=agent_name,
            tool_id=tool_id,
            status=AgentToolStatus.ABSTAIN,
            answer=None,
            facts={},
            evidence_refs=(),
            reason=reason,
            trace_ref=trace_ref,
            charter_version=charter_version,
            charter_sha256=charter_sha256,
            prompt_sha256=prompt_sha256,
            allowed_tools=agent.spec.conversation.tools if agent is not None else (),
        )


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _policy_attribution(agent: Agent) -> tuple[str, str, str]:

    policy = agent.spec.conversation_policy()
    return (
        str(policy["version"]),
        str(policy["charter_sha256"]),
        str(policy["prompt_sha256"]),
    )


def _evidence_refs(
    facts: Mapping[str, Any],
    *,
    agent_name: str,
) -> tuple[tuple[str, ...], int]:
    refs: list[str] = []
    raw = facts.get("evidence_refs")
    if isinstance(raw, list | tuple):
        refs.extend(item for item in raw if isinstance(item, str) and item)
    for key, value in facts.items():
        if (key.endswith("_ref") or key.endswith("_id")) and isinstance(value, str) and value:
            refs.append(f"{key}:{value}")
    if not refs:
        refs.append(agent_state_evidence_ref(agent_name, dict(facts)))
    unique = tuple(dict.fromkeys(refs))
    return unique[:_MAX_EVIDENCE_REFS], len(unique)


__all__ = ["AgentConversationToolRegistry", "AgentToolResult", "AgentToolStatus"]
