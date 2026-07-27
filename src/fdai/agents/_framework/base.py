"""Agent contract and base class.

The `Agent` class is the runtime shell; per-agent behavior lives in
subclasses under this package (added in Waves 2 through 5). `AgentSpec`
is the immutable declaration read by the registry - see
`docs/roadmap/agents/agent-pantheon.md` \u00a75.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.conversation_prompt import (
    MAX_CHARTER_PROMPT_CHARS,
    MAX_ROLE_DIRECTIVE_CHARS,
    ComposedConversationPrompt,
    ConversationSituation,
    compose_conversation_prompt,
)
from fdai.agents._framework.introspection import (
    INTROSPECTION_ERROR,
    REQUIRES_TYPED_PIPELINE,
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capability_sentence,
    is_action_intent,
)

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus

_LOG = logging.getLogger(__name__)

# Distinct-key cap on the measurable-behavior counter. The vocabulary is a
# fixed set of colon-namespaced keys, so this is a generous ceiling; its job
# is to contain a misuse (a key built from unbounded data) rather than bound
# normal use. New keys past the cap fold into a single overflow sentinel.
_MAX_BEHAVIOR_KEYS = 512
_BEHAVIOR_OVERFLOW_KEY = "behavior:overflow"
_MAX_CONVERSATION_TOOLS = 16
_MAX_TOOL_PURPOSE_CHARS = 160
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_CHARTER_VERSION = re.compile(r"^v[1-9][0-9]*$")
_FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class Layer(StrEnum):
    """Pantheon layers - see `agent-pantheon.md` \u00a74.

    - ``DOMAIN``: specialists (Njord / Freyr / Loki).
    - ``PIPELINE``: sensing / judgment / operations / interface.
    - ``GOVERNANCE``: staff (Odin / Mimir / Muninn / Saga / Norns).
    """

    DOMAIN = "domain"
    PIPELINE = "pipeline"
    GOVERNANCE = "governance"


@dataclass(frozen=True, slots=True)
class RateLimits:
    """Per-agent proposal caps (`agent-pantheon.md` \u00a78 default 20 / 100)."""

    per_minute: int = 20
    per_hour: int = 100


@dataclass(frozen=True, slots=True)
class ConversationTool:
    """One read-only, fact-scoped conversational tool."""

    tool_id: str
    purpose: str
    fact_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if _TOOL_ID.fullmatch(self.tool_id) is None:
            raise ValueError("conversation tool id MUST be a bounded ASCII identifier")
        if not self.purpose.strip() or len(self.purpose) > _MAX_TOOL_PURPOSE_CHARS:
            raise ValueError("conversation tool purpose MUST be bounded and non-empty")
        if not self.fact_keys or len(set(self.fact_keys)) != len(self.fact_keys):
            raise ValueError("conversation tool fact_keys MUST be non-empty and unique")
        if any(_FACT_KEY.fullmatch(key) is None for key in self.fact_keys):
            raise ValueError("conversation tool fact_keys MUST be bounded ASCII identifiers")


@dataclass(frozen=True, slots=True)
class ConversationCharter:
    """Server-owned, versioned instructions and read-only tool manifest.

    ``system_prompt`` is the immutable **baseline**: the layers every
    turn runs with. One turn's effective prompt is composed from it by
    :func:`~fdai.agents._framework.conversation_prompt.compose_conversation_prompt`,
    which may only add situational layers on top - see
    :meth:`compose_prompt`.
    """

    version: str
    system_prompt: str
    tool_specs: tuple[ConversationTool, ...]
    routing_examples: tuple[str, ...]
    role_directive: str = ""
    """Agent-specific mechanics layer; MUST also appear in ``system_prompt``."""

    def __post_init__(self) -> None:
        if _CHARTER_VERSION.fullmatch(self.version) is None:
            raise ValueError("conversation version MUST be a canonical vN identifier")
        if not self.system_prompt.strip() or len(self.system_prompt) > MAX_CHARTER_PROMPT_CHARS:
            raise ValueError("conversation system_prompt MUST be bounded and non-empty")
        if self.role_directive and (
            len(self.role_directive) > MAX_ROLE_DIRECTIVE_CHARS
            # The baseline is the composition floor, so a directive that is
            # declared but not baked into it would silently never reach a
            # model. Pin the two together instead of trusting the caller.
            or self.role_directive not in self.system_prompt
        ):
            raise ValueError("conversation role_directive MUST be bounded and part of the baseline")
        if not self.tool_specs or len(self.tool_specs) > _MAX_CONVERSATION_TOOLS:
            raise ValueError("conversation tools MUST contain between 1 and 16 items")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("conversation tools MUST be unique")
        if len(self.routing_examples) < 2 or any(
            not example.strip() for example in self.routing_examples
        ):
            raise ValueError("conversation routing_examples MUST contain English and Korean text")
        if not any(re.search(r"[A-Za-z]", example) for example in self.routing_examples) or not any(
            re.search(r"[가-힣]", example) for example in self.routing_examples
        ):
            raise ValueError("conversation routing_examples MUST contain English and Korean text")

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(tool.tool_id for tool in self.tool_specs)

    def tool(self, tool_id: str) -> ConversationTool | None:
        return next((tool for tool in self.tool_specs if tool.tool_id == tool_id), None)

    def compose_prompt(
        self,
        situation: ConversationSituation | None = None,
    ) -> ComposedConversationPrompt:
        """Compose this turn's prompt for ``situation``.

        ``None`` composes the baseline, so a caller with no situational
        signal gets exactly the charter prompt.
        """
        return compose_conversation_prompt(
            baseline_prompt=self.system_prompt,
            situation=situation or ConversationSituation.baseline(),
        )


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Immutable declaration of one pantheon agent.

    The registry rejects any spec whose ``owns`` overlaps with another
    agent's ``owns`` (single-writer invariant, see
    ``docs/roadmap/agents/agent-pantheon.md`` \u00a76.1).
    """

    name: str
    layer: Layer
    reports_to: str | None
    owns: tuple[str, ...]
    conversation: ConversationCharter
    """ObjectType names this agent is the single writer of."""
    executes: tuple[str, ...] = ()
    """ActionType names this agent may execute as the sole mutation principal."""
    initiates: tuple[str, ...] = ()
    """ActionType names this agent may propose (initiator role)."""
    subscribes: tuple[str, ...] = ()
    publishes: tuple[str, ...] = ()
    question_domains: tuple[str, ...] = ()
    owns_code_paths: tuple[str, ...] = ()
    hot_path_llm: bool = False
    """True only for Bragi (translator) and Forseti (T2 abstain)."""
    off_path_llm: bool = False
    """True only for Norns (batch discovery)."""
    rate_limits: RateLimits = field(default_factory=RateLimits)
    hard_dependency: bool = False
    """Saga and Vidar only: without them, mutation is refused / demoted."""

    def __post_init__(self) -> None:
        # publishes MUST equal the topic form of owns (single-writer
        # invariant). We derive this at spec-build time so the registry
        # never has to reconcile two lists.
        object.__setattr__(
            self,
            "publishes",
            tuple(f"object.{_kebab(o)}" for o in self.owns),
        )

    def conversation_policy(self) -> dict[str, Any]:
        """Return public attribution for the complete immutable charter."""
        charter = {
            "version": self.conversation.version,
            "agent": self.name,
            "layer": self.layer.value,
            "reports_to": self.reports_to,
            "owns": list(self.owns),
            "executes": list(self.executes),
            "initiates": list(self.initiates),
            "subscribes": list(self.subscribes),
            "question_domains": list(self.question_domains),
            "hot_path_llm": self.hot_path_llm,
            "off_path_llm": self.off_path_llm,
            "hard_dependency": self.hard_dependency,
            "system_prompt": self.conversation.system_prompt,
            "tools": [
                {
                    "id": tool.tool_id,
                    "purpose": tool.purpose,
                    "fact_keys": list(tool.fact_keys),
                }
                for tool in self.conversation.tool_specs
            ],
            "routing_examples": list(self.conversation.routing_examples),
        }
        canonical = json.dumps(
            charter,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "version": self.conversation.version,
            "charter_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "prompt_sha256": hashlib.sha256(
                self.conversation.system_prompt.encode("utf-8")
            ).hexdigest(),
            "tools": list(self.conversation.tools),
        }


class Agent:
    """Runtime base class for a pantheon agent.

    Subclasses live under `src/fdai/agents/` (one file per canonical name,
    added wave-by-wave). Wave 1 ships stub subclasses that implement no
    behavior beyond registering their `AgentSpec`.
    """

    spec: AgentSpec

    #: Typed pub/sub port. Publishing agents bind a concrete
    #: :class:`~fdai.agents._framework.bus.PantheonBus` (``InMemoryBus`` in tests,
    #: ``EventBusBridge`` in production) via :meth:`bind_bus`; agents that
    #: never publish leave it ``None``. Declared on the base so the
    #: composition root (:class:`~fdai.agents._framework.runtime.PantheonRuntime`)
    #: can bind every agent uniformly without duck-typing.
    bus: PantheonBus | None = None

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        # Measurable-behavior counter. Every agent records what it *did*
        # (verdict:auto, hil_pending, security_event, candidate:new, ...) so
        # a scenario test can assert on observed behaviour and its invariants
        # instead of reaching into private state. Surfaced through
        # :meth:`behavior_snapshot` and :meth:`health`, and merged into
        # ``PantheonRuntime.health()`` per agent.
        self._behavior: Counter[str] = Counter()

    def record_behavior(self, key: str, count: int = 1) -> None:
        """Increment the measurable-behavior counter for ``key``.

        Keys are stable, colon-namespaced strings (``verdict:auto``,
        ``candidate:threshold_adjustment``) so a scenario harness or the KPI
        collector reads a consistent vocabulary. Recording is best-effort
        observability - it MUST NOT change a decision.

        **Decision semantics.** A counter measures what the agent *decided*
        (a verdict issued, an alert raised), recorded independent of whether
        a downstream publish then succeeds. Delivery is a separate concern
        measured by the bus metrics (``published`` / ``publish_errors``), so
        the two never skew each other and a bus-less unit still measures the
        decision.

        Robust by construction:

        - lazy-inits the counter, so it works even if a subclass skipped
          ``super().__init__`` (a defect elsewhere must not make observability
          raise);
        - caps the distinct-key space at :data:`_MAX_BEHAVIOR_KEYS`. The
          vocabulary is meant to be fixed, but a caller that mistakenly builds
          a key from unbounded data (a resource id) would otherwise explode
          the counter's key space. Past the cap, a new key is folded into a
          bounded ``behavior:overflow`` sentinel instead of being added.
        """
        counter = getattr(self, "_behavior", None)
        if counter is None:
            counter = Counter()
            self._behavior = counter
        if count <= 0:
            # A measurement counter never decreases; a non-positive count is a
            # caller mistake, ignored (best-effort observability never raises).
            return
        if key not in counter and len(counter) >= _MAX_BEHAVIOR_KEYS:
            counter[_BEHAVIOR_OVERFLOW_KEY] += count
            return
        counter[key] += count

    def behavior_snapshot(self) -> dict[str, int]:
        """Return a copy of the measurable-behavior counters.

        The single seam a scenario test reads to measure what an agent did.
        A copy, so a caller cannot mutate the agent's live counters. Robust to
        a missing counter (returns an empty dict rather than raising).
        """
        return dict(getattr(self, "_behavior", Counter()))

    # --- proposal rate limiting (agent-pantheon.md 7.9) -----------------

    def _proposal_rate_limiter(self) -> Any:
        """Lazily build (and cache) this agent's proposal rate limiter.

        Lazy so a subclass that skipped ``super().__init__`` still gets one,
        and lazily imported so the ``base <- rate_limiter`` module cycle never
        forms (``rate_limiter`` imports :class:`RateLimits` from here). Tests
        may inject a deterministic-clock limiter by assigning
        ``agent._proposal_limiter`` before the first proposal.
        """
        limiter = getattr(self, "_proposal_limiter", None)
        if limiter is None:
            from fdai.agents._framework.rate_limiter import RateLimiter

            limiter = RateLimiter.from_limits(self.spec.rate_limits)
            self._proposal_limiter = limiter
        return limiter

    async def _publish_proposal(self, topic: str, payload: dict[str, Any]) -> bool:
        """Publish a discretionary proposal, honoring the agent's ``rate_limits``.

        Proposals (rule candidates, chaos experiments, domain advisories) are
        an agent's discretionary emissions; a malfunctioning or compromised
        agent could flood them. When the per-minute / per-hour budget
        (:class:`AgentSpec.rate_limits`, ``agent-pantheon.md`` 7.9) is
        exhausted, the proposal is NOT published and the drop is recorded as
        ``rate_limit_exceeded`` so the spike surfaces in health / KPI. Returns
        ``True`` when published, ``False`` when rate-limited or bus-less.

        Safety-critical emissions (verdicts, action runs, approvals, audit
        entries) are NOT proposals and MUST NOT go through this path - they
        publish via :attr:`bus` directly so a budget can never shed a
        pipeline-critical message.
        """
        bus = getattr(self, "bus", None)
        if bus is None:
            return False
        if not self._proposal_rate_limiter().allow():
            self.record_behavior("rate_limit_exceeded")
            _LOG.warning(
                "proposal_rate_limited",
                extra={"agent": self.spec.name, "topic": topic},
            )
            return False
        await bus.publish(self.spec.name, topic, payload)
        return True

    def bind_bus(self, bus: PantheonBus) -> None:
        """Bind the typed pub/sub port.

        Publishing subclasses may override to keep a narrower type, but
        the base implementation is sufficient: it stores the bus so
        :meth:`Agent.on_typed_message` handlers can publish. Idempotent -
        re-binding replaces the bus.
        """
        self.bus = bus

    # --- typed port (hot-path pub/sub) ---------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a message from a typed topic this agent subscribes to.

        Wave 1 stubs default to a no-op. Behavior lands in later waves.
        """
        return None

    # --- conversational port (LLM-backed NL Q&A) -----------------------

    async def on_conversation_turn(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        """Answer a natural-language query directed at this agent.

        This is the agent's conversational port (agent-pantheon.md 6.2):
        a read-only, request-response NL interface reachable through Bragi
        for operators and for agent-to-agent (A2A) NL introspection. It
        answers questions over the data the agent owns; it MUST NOT mutate.

        Flow:

        1. **MUST-NOT-bypass guard (7.7).** A request phrased as a command
           ("restart vm-1") is not answered here - it abstains with
           :data:`~fdai.agents._framework.introspection.REQUIRES_TYPED_PIPELINE` so
           the caller re-enters the typed pipeline with the operator as
           ``initiator_principal``. The port describes actions, never runs
           them.
        2. **Introspection.** Otherwise delegate to :meth:`introspect`,
           which each concrete agent overrides to ground the answer in its
           owned runtime state. The base implementation answers from the
           immutable ``AgentSpec`` (role / ownership / capabilities).

        The returned envelope carries ``primary_agent``, ``answer``,
        ``facts`` (structured evidence, always present for A2A consumers),
        ``trace_ref`` (the shared correlation trace - the only thing the
        two ports share), and ``abstain_reason`` (set only when
        ``answer`` is ``None``).

        The prompt handed to the answering layer is composed per turn:
        the immutable charter baseline plus the situational layers the
        turn context selects (peer vs operator audience, deliberation
        phase and tier, tool scope, locale, evidence gap, command
        intent). Composition is additive, so the situation can tighten
        the charter but never loosen it.
        """
        charter = self.spec.conversation
        action_intent = is_action_intent(question)
        tool_id = context.get("conversation_tool")
        tool = charter.tool(tool_id) if isinstance(tool_id, str) else None
        # Lazily imported: pantheon.py builds on this module, so a module
        # level import would close the cycle. The roster is what turns a
        # shape check on an agent name into a membership check.
        from fdai.agents._framework.pantheon import PANTHEON_NAMES

        composed = charter.compose_prompt(
            ConversationSituation.from_context(
                context,
                allowed_tools=charter.tools,
                tool_fact_keys=tool.fact_keys if tool is not None else (),
                known_agents=PANTHEON_NAMES,
                action_intent=action_intent,
                evidence_available=(
                    context.get("evidence_available") is not False
                    and self.conversation_evidence_available(context)
                ),
            )
        )
        policy_context = {
            **context,
            "agent_system_prompt": composed.text,
            "agent_allowed_tools": charter.tools,
            "agent_prompt_composition": composed.attribution(),
        }
        if action_intent:
            return self._conversation_envelope(
                IntrospectionResult.abstain(
                    REQUIRES_TYPED_PIPELINE,
                    facts={"question": question},
                ),
                policy_context,
                requires_typed_pipeline=True,
            )
        try:
            result = await self.introspect(question, policy_context)
        except Exception as exc:  # noqa: BLE001 - port availability guard
            # One agent's introspection bug MUST NOT crash the shared
            # conversational port (an operator ask or an A2A introspection
            # would take the whole port down). Degrade to an honest abstain
            # and log the failure by type only - never the exception value,
            # which may carry owned data.
            _LOG.warning(
                "introspect_failed",
                extra={"agent": self.spec.name, "error_type": type(exc).__name__},
            )
            result = IntrospectionResult.abstain(INTROSPECTION_ERROR)
        if tool_id is not None and isinstance(tool_id, str):
            result = (
                _project_tool_result(result, tool)
                if tool is not None
                else IntrospectionResult.abstain("unknown_tool")
            )
        return self._conversation_envelope(result, policy_context)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        """Answer a read-only introspection question from owned state.

        The base implementation answers from the agent's immutable
        ``AgentSpec`` (its role, ownership, and the question domains it
        serves), so every agent can describe itself even before it holds
        runtime state. Concrete agents override this to ground answers in
        the data they own (cost samples, audit chain, action runs, ...),
        calling ``super().introspect(...)`` for the capability fallback.
        """
        return IntrospectionResult(
            answer=capability_sentence(self.spec),
            facts=capability_facts(self.spec),
        )

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Report whether owned runtime evidence backs this turn.

        Selects the ``evidence_gap`` prompt layer, which tells the agent
        to name the missing evidence and abstain rather than reason from
        general knowledge. The prompt is composed before
        :meth:`introspect` runs, so the agent - not the answer - is the
        only thing that can know this up front.

        The base returns ``True``: an agent always owns its ``AgentSpec``
        and can describe itself. An agent whose answers depend on
        accumulated runtime state overrides this and reports ``False``
        while that state is empty.
        """
        return True

    def _conversation_envelope(
        self,
        result: IntrospectionResult,
        context: dict[str, Any],
        *,
        requires_typed_pipeline: bool = False,
    ) -> dict[str, Any]:
        """Wrap an :class:`IntrospectionResult` in the port response shape."""
        trace_ref = str(
            context.get("trace_ref")
            or context.get("correlation_id")
            or context.get("session_id")
            or ""
        )
        facts = dict(result.facts)
        refs = facts.get("evidence_refs")
        if not isinstance(refs, list | tuple) or not any(str(ref) for ref in refs):
            facts["evidence_refs"] = [agent_state_evidence_ref(self.spec.name, facts)]
        envelope: dict[str, Any] = {
            "primary_agent": self.spec.name,
            "answer": result.answer,
            "facts": facts,
            "trace_ref": trace_ref,
            "abstain_reason": result.abstain_reason,
            "conversation_policy": {
                **self.spec.conversation_policy(),
            },
        }
        # Which layers actually ran this turn, by id and digest only. The
        # charter policy above stays the immutable contract identity; this
        # is the per-turn replay record, and it never carries prompt text.
        composition = context.get("agent_prompt_composition")
        if isinstance(composition, dict):
            envelope["prompt_composition"] = composition
        if requires_typed_pipeline:
            envelope["requires_typed_pipeline"] = True
        return envelope

    # --- lifecycle & health --------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return the health snapshot Heimdall probes (Wave 3+)."""
        return {"agent": self.spec.name, "status": "stub", "behavior": self.behavior_snapshot()}


def _kebab(name: str) -> str:
    """Camel or PascalCase ObjectType name -> kebab topic form.

    Examples:
        ``Event`` -> ``event``
        ``ActionRun`` -> ``action-run``
        ``SecurityEvent`` -> ``security-event``
    """
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


def _project_tool_result(
    result: IntrospectionResult,
    tool: ConversationTool,
) -> IntrospectionResult:
    """Project a broad owned-state answer onto one declared tool scope."""
    if result.answer is None:
        return result
    allowed = {"agent", "evidence_refs", *tool.fact_keys}
    facts = {key: value for key, value in result.facts.items() if key in allowed}
    if not any(key in facts for key in tool.fact_keys):
        return IntrospectionResult.abstain("no_tool_data", facts=facts)
    scoped_values = [facts[key] for key in tool.fact_keys if key in facts]
    if scoped_values and all(value is False or value is None for value in scoped_values):
        return IntrospectionResult(
            answer=f"{tool.purpose} No owned data is currently available.",
            facts=facts,
        )
    return IntrospectionResult(
        answer=f"{tool.purpose} {result.answer}",
        facts=facts,
    )


__all__ = [
    "Agent",
    "AgentSpec",
    "ConversationCharter",
    "ConversationTool",
    "Layer",
    "RateLimits",
]
