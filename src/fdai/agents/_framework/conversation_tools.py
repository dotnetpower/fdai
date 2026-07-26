"""Registered read-only tool surface for fixed Pantheon agent charters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

_MAX_QUESTION_CHARS = 2_000
_MAX_TRACE_REF_CHARS = 256
_MAX_OUTPUT_BYTES = 65_536


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
        if timeout_seconds <= 0:
            raise ValueError("agent conversation tool timeout MUST be positive")
        self._agents = dict(agents)
        self._disabled = disabled_agents
        self._timeout_seconds = timeout_seconds
        self._owners: dict[str, str] = {}
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
        owner = self._owners.get(tool_id)
        if owner is None:
            return self._abstain(agent_name, tool_id, "unknown_tool", trace_ref)
        if owner != agent_name:
            return self._abstain(agent_name, tool_id, "wrong_owner", trace_ref)
        if agent_name in self._disabled or agent_name not in self._agents:
            return self._abstain(agent_name, tool_id, "agent_disabled", trace_ref)
        agent = self._agents[agent_name]
        try:
            async with asyncio.timeout(self._timeout_seconds):
                envelope = await agent.on_conversation_turn(
                    question,
                    {"trace_ref": trace_ref, "conversation_tool": tool_id},
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            agent.record_behavior(f"conversation_tool:{tool_id}:timeout")
            return self._abstain(agent_name, tool_id, "timeout", trace_ref)
        except Exception:
            agent.record_behavior(f"conversation_tool:{tool_id}:error")
            return self._abstain(agent_name, tool_id, "error", trace_ref)

        answer = envelope.get("answer")
        facts = envelope.get("facts")
        safe_answer = answer if isinstance(answer, str) else None
        safe_facts = dict(facts) if isinstance(facts, Mapping) else {}
        result_trace_ref = str(envelope.get("trace_ref") or trace_ref)
        serialized = json.dumps(
            {"answer": safe_answer, "facts": safe_facts, "trace_ref": result_trace_ref},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
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
        abstain_reason = envelope.get("abstain_reason")
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
        return AgentToolResult(
            agent=agent_name,
            tool_id=tool_id,
            status=AgentToolStatus.OK,
            answer=safe_answer,
            facts=safe_facts,
            evidence_refs=_evidence_refs(safe_facts, agent_name=agent_name),
            reason=None,
            trace_ref=result_trace_ref,
            charter_version=charter_version,
            charter_sha256=charter_sha256,
            prompt_sha256=prompt_sha256,
            allowed_tools=agent.spec.conversation.tools,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "registered": len(self._owners),
            "available": sum(owner in self._agents for owner in self._owners.values()),
            "disabled": sum(owner not in self._agents for owner in self._owners.values()),
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


def _policy_attribution(agent: Agent) -> tuple[str, str, str]:
    policy = agent.spec.conversation_policy()
    return (
        str(policy["version"]),
        str(policy["charter_sha256"]),
        str(policy["prompt_sha256"]),
    )


def _evidence_refs(facts: Mapping[str, Any], *, agent_name: str) -> tuple[str, ...]:
    refs: list[str] = []
    raw = facts.get("evidence_refs")
    if isinstance(raw, list | tuple):
        refs.extend(str(item) for item in raw[:20] if str(item))
    for key, value in facts.items():
        if (key.endswith("_ref") or key.endswith("_id")) and isinstance(value, str) and value:
            refs.append(f"{key}:{value}")
    if not refs:
        refs.append(f"agent-spec:{agent_name}")
    return tuple(dict.fromkeys(refs))


__all__ = ["AgentConversationToolRegistry", "AgentToolResult", "AgentToolStatus"]
