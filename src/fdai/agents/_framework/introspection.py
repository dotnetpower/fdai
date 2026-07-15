"""Conversational-port introspection contract.

The pantheon's second port (``agent-pantheon.md`` 6.2) is a request-response
natural-language interface. Every agent answers questions about the data it
owns plus the code it owns (``owns_code_paths`` RAG), reachable through Bragi
for operators and for agent-to-agent (A2A) NL introspection.

This module holds the shared, LLM-free scaffolding both the base
:class:`~fdai.agents._framework.base.Agent` and each concrete agent build on:

- :class:`IntrospectionResult` - the value an agent's ``introspect`` returns.
- :func:`is_action_intent` - the MUST-NOT-bypass guard (7.7): the
  conversational port may *describe* actions but never execute one; a request
  phrased as a command re-enters the typed pipeline instead of being answered.
- :func:`capability_facts` / :func:`capability_sentence` - the default
  self-description every agent can answer from its immutable ``AgentSpec``.

Rendering here is deterministic (no model call): a fork swaps in an LLM-backed
narrator over the same ``facts`` without changing this contract.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# MUST-NOT-bypass guard (agent-pantheon.md 7.7)
# ---------------------------------------------------------------------------

# Imperative verbs that denote a *mutation* request rather than a question.
# A conversational turn that starts with one of these is a command: the port
# refuses to execute and signals the caller to re-enter the typed pipeline.
_ACTION_VERBS: frozenset[str] = frozenset(
    {
        "restart",
        "reboot",
        "delete",
        "remove",
        "drop",
        "destroy",
        "scale",
        "resize",
        "failover",
        "remediate",
        "encrypt",
        "execute",
        "run",
        "apply",
        "deploy",
        "provision",
        "rollback",
        "revert",
        "approve",
        "reject",
        "disable",
        "enable",
        "create",
        "kill",
        "drain",
        "terminate",
        "mutate",
        "patch",
        "update",
        "set",
        "start",
        "stop",
        "promote",
        "retire",
        "override",
        "flush",
        "purge",
        "grant",
        "revoke",
        "open",
        "transition",
        "assign",
    }
)

# Polite prefixes stripped before inspecting the leading verb, so
# "please restart vm-1" and "can you delete rg-x" are still caught.
_FILLER_PREFIX: frozenset[str] = frozenset(
    {"please", "can", "could", "would", "you", "kindly", "pls", "hey", "ok", "okay"}
)

# Verbs that double as a noun / adjective, so a leading occurrence is NOT
# automatically a command ("set of rules?", "run status?", "update history?").
# For these, only an imperative phrasing (no question mark, no interrogative
# marker) counts as a mutation command - otherwise it is introspection. Every
# entry is also in ``_ACTION_VERBS`` so a genuine command still maps.
_AMBIGUOUS_ACTION_VERBS: frozenset[str] = frozenset(
    {"set", "start", "stop", "update", "run", "apply", "patch", "drain"}
)

# Interrogative markers that flip an ambiguous-verb lead back to a question.
_QUESTION_MARKERS: frozenset[str] = frozenset(
    {
        "what",
        "why",
        "who",
        "how",
        "when",
        "which",
        "where",
        "whose",
        "whom",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "show",
        "list",
        "tell",
        "explain",
        "describe",
        "status",
        "count",
        "many",
        "much",
        "any",
    }
)

#: Defensive cap on how much of a question is tokenized. The conversational
#: port is an operator / agent input boundary; an unbounded question would let
#: a caller inflate tokenization cost. A real NL query is far shorter.
_MAX_QUESTION_LEN = 2000

#: Cap on how many owned identifiers an agent lists inside ``facts``. Bounds
#: both the payload size and the incidental exposure of every id; the paired
#: count field still reports the true total, and the operator narrows to a
#: specific id by naming it (see :func:`mentioned`).
_FACTS_LIST_CAP = 20

_WORD_RE = re.compile(r"[a-z0-9-]+")


def _tokens(question: str) -> list[str]:
    """Tokenize a bounded prefix of ``question`` (defensive input cap)."""
    return _WORD_RE.findall(question[:_MAX_QUESTION_LEN].lower())


def is_action_intent(question: str) -> bool:
    """Return ``True`` when ``question`` is a mutation command, not a query.

    Deterministic and conservative-by-safety: a leading imperative verb
    (after stripping polite filler) means the request wants to *change*
    something, which the conversational port MUST NOT do itself
    (agent-pantheon.md 7.7). Interrogatives ("what/why/who/show/list/...")
    fall through as introspection. A verb that doubles as a noun
    ("set of rules?", "run status?") is a command only when phrased
    imperatively - no question mark and no interrogative marker.
    """
    verb = leading_verb(question)
    if verb is None:
        return False
    if verb in _AMBIGUOUS_ACTION_VERBS:
        if "?" in question[:_MAX_QUESTION_LEN]:
            return False
        if any(token in _QUESTION_MARKERS for token in _tokens(question)):
            return False
        return True
    return verb in _ACTION_VERBS


def leading_verb(question: str) -> str | None:
    """Return the first non-filler token of ``question`` (lower-cased), or None.

    Shared by :func:`is_action_intent` and Bragi's proposal translation so the
    "is this a command?" test and the "which action?" mapping read the same
    leading verb (e.g. ``restart`` from ``please restart vm-1``).
    """
    for token in _tokens(question):
        if token in _FILLER_PREFIX:
            continue
        return str(token)
    return None


def mentioned(question: str, candidates: Any) -> list[str]:
    """Return the ``candidates`` whose name appears as a token in ``question``.

    Case-insensitive whole-token match, used by concrete agents to scope an
    introspection answer to a resource / scope / id the operator named
    (e.g. "cost for rg-abc" -> the ``rg-abc`` scope). Order follows
    ``candidates`` for determinism.
    """
    tokens = set(_tokens(question))
    return [c for c in candidates if str(c).lower() in tokens]


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


# ---------------------------------------------------------------------------
# Default capability self-description (every agent, from its AgentSpec)
# ---------------------------------------------------------------------------


def capability_facts(spec: AgentSpec) -> dict[str, Any]:
    """Structured self-description derived from an agent's immutable spec."""
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
    "is_action_intent",
    "leading_verb",
    "mentioned",
    "capped_list",
    "capability_facts",
    "capability_sentence",
]
