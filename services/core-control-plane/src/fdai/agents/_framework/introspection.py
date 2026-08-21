"""Conversational-port introspection contract.

The pantheon's second port (``agent-pantheon.md`` 6.2) is a request-response
natural-language interface. Every agent answers questions about the data it
owns plus the code it owns (``owns_code_paths`` RAG), reachable through Bragi
for operators and for agent-to-agent (A2A) NL introspection.

This module holds the shared, LLM-free scaffolding both the base
:class:`~fdai.agents._framework.base.Agent` and each concrete agent build on:

- :class:`IntrospectionResult` - the value an agent's ``introspect`` returns.
- :func:`capability_facts` / :func:`capability_sentence` - the default
  self-description every agent can answer from its immutable ``AgentSpec``.

Rendering here is deterministic (no model call): a fork swaps in an LLM-backed
narrator over the same ``facts`` without changing this contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.agents._framework.base import AgentSpec

#: Abstain reason emitted when a conversational request is actually a command.
#: The port answers questions; an action must re-enter the typed pipeline with
#: the operator as ``initiator_principal`` (agent-pantheon.md 7.7).
REQUIRES_TYPED_PIPELINE = "requires_typed_pipeline"

#: Abstain reason when the agent has no data for the question.
NO_DATA = "no_data"

#: Abstain reason when an agent's ``introspect`` raised - the shared port
#: degrades to an honest abstain instead of crashing (see
#: :meth:`fdai.agents._framework.base.Agent.on_conversation_turn`).
INTROSPECTION_ERROR = "introspection_error"


@dataclass(frozen=True, slots=True)
class IntrospectionResult:
    """One agent's answer to a natural-language introspection request.

    ``answer`` is the rendered natural-language string (``None`` when the
    agent abstains). ``facts`` is the structured, machine-readable evidence
    the answer is grounded in - always present so an A2A caller can consume
    the data without parsing prose. ``abstain_reason`` is set only when
    ``answer`` is ``None``.
    """

    answer: str | None
    facts: dict[str, Any] = field(default_factory=dict)
    abstain_reason: str | None = None

    @classmethod
    def abstain(cls, reason: str, *, facts: dict[str, Any] | None = None) -> IntrospectionResult:
        return cls(answer=None, facts=facts or {}, abstain_reason=reason)


#: Defensive cap on how much of a question is tokenized. The conversational
#: port is an operator / agent input boundary; an unbounded question would let
#: a caller inflate tokenization cost. A real NL query is far shorter.
_MAX_QUESTION_LEN = 2000

#: Cap on how many owned identifiers an agent lists inside ``facts``. Bounds
#: both the payload size and the incidental exposure of every id; the paired
#: count field still reports the true total, and the operator narrows to a
#: specific id by naming it (see :func:`mentioned`).
_FACTS_LIST_CAP = 20

_IDENTIFIER_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def mentioned(question: str, candidates: Any) -> list[str]:
    """Return the ``candidates`` whose name appears as a token in ``question``.

    Case-insensitive whole-token match, used by concrete agents to scope an
    introspection answer to a resource / scope / id the operator named
    (e.g. "cost for rg-abc" -> the ``rg-abc`` scope). Order follows
    ``candidates`` for determinism.
    """
    identifiers = set(_IDENTIFIER_RE.findall(question[:_MAX_QUESTION_LEN].lower()))
    return [c for c in candidates if str(c).lower() in identifiers]


def semantic_intents(context: dict[str, Any]) -> frozenset[str]:
    """Return validated machine intent tokens supplied by Bragi's judgment."""

    primary = context.get("semantic_primary_intent")
    facets = context.get("semantic_requested_facets", ())
    values = ([primary] if isinstance(primary, str) else []) + (
        list(facets)
        if isinstance(facets, tuple | list) and all(isinstance(item, str) for item in facets)
        else []
    )
    return frozenset(values)


def capped_list(items: Any) -> list[str]:
    """Return the first :data:`_FACTS_LIST_CAP` items as strings.

    Bounds both the ``facts`` payload size and the incidental exposure of
    every owned identifier when an agent lists what it tracks. The paired
    count field an agent emits still reports the true total.
    """
    out: list[str] = []
    for index, item in enumerate(items):
        if index >= _FACTS_LIST_CAP:
            break
        out.append(str(item))
    return out


def agent_state_evidence_ref(agent_name: str, facts: dict[str, Any]) -> str:
    """Return a deterministic reference for one normalized agent fact snapshot."""
    canonical_facts = {key: value for key, value in facts.items() if key != "evidence_refs"}
    canonical = json.dumps(
        canonical_facts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"agent-state:{agent_name}:sha256:{digest}"


# ---------------------------------------------------------------------------
# Default capability self-description (every agent, from its AgentSpec)
# ---------------------------------------------------------------------------


def capability_facts(spec: AgentSpec) -> dict[str, Any]:
    """Structured self-description derived from an agent's immutable spec."""
    conversation_policy = spec.conversation_policy()
    return {
        "agent": spec.name,
        "layer": spec.layer.value,
        "reports_to": spec.reports_to,
        "owns": list(spec.owns),
        "question_domains": list(spec.question_domains),
        "subscribes": list(spec.subscribes),
        "publishes": list(spec.publishes),
        "hot_path_llm": spec.hot_path_llm,
        "off_path_llm": spec.off_path_llm,
        "hard_dependency": spec.hard_dependency,
        "conversation_tools": list(spec.conversation.tools),
        "conversation_charter_version": conversation_policy["version"],
        "conversation_charter_sha256": conversation_policy["charter_sha256"],
        "conversation_prompt_sha256": conversation_policy["prompt_sha256"],
    }


def capability_sentence(spec: AgentSpec) -> str:
    """Render a deterministic one-line self-description from a spec."""
    owns = ", ".join(spec.owns) if spec.owns else "no object types"
    domains = ", ".join(spec.question_domains) if spec.question_domains else "none"
    return (
        f"I am {spec.name}, a {spec.layer.value}-layer agent. "
        f"I own {owns}. I can answer questions about: {domains}."
    )


__all__ = [
    "IntrospectionResult",
    "REQUIRES_TYPED_PIPELINE",
    "NO_DATA",
    "INTROSPECTION_ERROR",
    "mentioned",
    "semantic_intents",
    "capped_list",
    "agent_state_evidence_ref",
    "capability_facts",
    "capability_sentence",
]
