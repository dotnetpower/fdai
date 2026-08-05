"""Selected-agent charter and turn-constraint composition for chat prompts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from fdai.agents import AgentSpec, ConversationSituation

_TURN_CONSTRAINTS: Final[Mapping[str, str]] = {
    "evidence_gap": (
        "that agent held no owned runtime evidence, so name the gap instead of covering it"
    ),
    "budget_denied": (
        "the escalation budget was spent, so do not present the answer as a deeper analysis"
    ),
    "action_intent": "the request was a command, so route it rather than answering it",
}


def agent_turn_constraints(
    evidence: Mapping[str, Any],
    *,
    constraints: Mapping[str, str] = _TURN_CONSTRAINTS,
) -> str:
    """Render the constraints the answering agent ran under, if any."""
    composition = evidence.get("prompt_composition")
    if not isinstance(composition, Mapping):
        return ""
    layers = composition.get("layers")
    if not isinstance(layers, list):
        return ""
    applied = [constraints[layer] for layer in layers if layer in constraints]
    if not applied:
        return ""
    return "Constraints on that agent's turn: " + "; ".join(applied) + ".\n"


def selected_agent_charter(
    view_context: Mapping[str, Any],
    *,
    agent_specs: Mapping[str, AgentSpec],
    turn_constraints: Callable[[Mapping[str, Any]], str],
    locale: str | None = None,
    session_target: str | None = None,
) -> str | None:
    """Compose a verified server-owned charter for the selected agent."""
    evidence = view_context.get("_agent_evidence")
    if not isinstance(evidence, Mapping):
        return None
    agent_name = evidence.get("primary_agent")
    if not isinstance(agent_name, str):
        return None
    spec = agent_specs.get(agent_name)
    if spec is None:
        return None
    policy = evidence.get("conversation_policy")
    expected_policy = spec.conversation_policy()
    if not isinstance(policy, Mapping) or dict(policy) != expected_policy:
        return None
    tools = ", ".join(spec.conversation.tools)
    composed = spec.conversation.compose_prompt(
        ConversationSituation.from_context({"locale": locale} if locale else {})
    )
    if session_target == agent_name:
        narrator_identity = (
            f"Dedicated selected-agent session: speak as {agent_name} in first person and "
            f"preserve that identity for this turn. If asked your name or identity, answer "
            f"{agent_name}. Do not identify as Bragi. Bragi's global instructions remain "
            "the read-only safety, evidence, RBAC, and typed-pipeline boundary."
        )
    else:
        narrator_identity = (
            "Bragi remains the read-only narrator. Apply this server-owned charter only to "
            "the answer's role, scope, and voice."
        )
    return (
        f"Selected accountable agent: {agent_name}.\n"
        f"{narrator_identity} It cannot override the global safety, "
        "evidence, RBAC, or typed-pipeline rules, and it is not evidence. Do not claim "
        "a tool ran unless the supplied agent evidence proves it.\n"
        f"Charter version: {spec.conversation.version}. Allowed read tools: {tools}.\n"
        f"{turn_constraints(evidence)}"
        f"Agent charter:\n{composed.text}"
    )
