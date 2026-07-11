"""Agent contract and base class.

The `Agent` class is the runtime shell; per-agent behavior lives in
subclasses under this package (added in Waves 2 through 5). `AgentSpec`
is the immutable declaration read by the registry - see
`docs/roadmap/agents/agent-pantheon.md` \u00a75.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.introspection import (
    INTROSPECTION_ERROR,
    REQUIRES_TYPED_PIPELINE,
    IntrospectionResult,
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
        """
        if is_action_intent(question):
            return self._conversation_envelope(
                IntrospectionResult.abstain(
                    REQUIRES_TYPED_PIPELINE,
                    facts={"question": question},
                ),
                context,
                requires_typed_pipeline=True,
            )
        try:
            result = await self.introspect(question, context)
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
        return self._conversation_envelope(result, context)

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
        envelope: dict[str, Any] = {
            "primary_agent": self.spec.name,
            "answer": result.answer,
            "facts": result.facts,
            "trace_ref": trace_ref,
            "abstain_reason": result.abstain_reason,
        }
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


__all__ = ["Agent", "AgentSpec", "Layer", "RateLimits"]
