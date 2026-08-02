"""Odin - Master Planner (Wave 4 behavior).

Odin arbitrates cross-vertical priority conflicts. When Forseti emits
an ArbitrationRequest (verdict with ``domain_conflict: true``), Odin
resolves it with a deterministic **multi-objective** arbiter loaded at
boot (default weights derived from ``resilience > security >
change_safety > cost > capacity``). Fork adapters override the priority
order or the weights via config.

The arbiter is a strict superset of the legacy priority table: with equal
impacts it reproduces the priority-order winner, but when a conflict
carries measured impact magnitudes it scores ``weight * impact`` per
domain and escalates near-ties to HIL instead of silently picking (see
:mod:`fdai.agents.arbitration`).

Temporal fairness (issue #4) is opt-in: a fork can bind a
:class:`DecisionHistory` seam and a
:class:`~fdai.agents.arbitration.TemporalPolicy` (for example
:class:`~fdai.agents.arbitration.AlternatingFairnessPolicy` or
:class:`~fdai.agents.arbitration.HysteresisPolicy`). Upstream default
binds :class:`NoopDecisionHistory`, which returns an empty history and
therefore reproduces today's stateless behavior exactly - no test or
downstream consumer of :class:`Odin` changes shape.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fdai.agents._framework.arbitration import (
    _DEFAULT_PRIORITY,
    ArbitrationOutcome,
    MultiObjectiveArbiter,
    RecentDecision,
    TemporalPolicy,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult, capability_facts
from fdai.agents._framework.pantheon import _ODIN
from fdai.agents._framework.vertical_precedence import CrossVerticalPrecedence

#: Bounded outcome vocabulary for the portfolio monitor. Anything a
#: producer sends outside it folds into ``unknown`` rather than growing
#: the counter's key space.
_PORTFOLIO_OUTCOMES = frozenset({"auto", "hil", "deny", "admit", "hold", "unknown"})


@runtime_checkable
class DecisionHistory(Protocol):
    """Provide a bounded, replayable window of past arbitrations.

    Backed by the append-only audit log in a real fork; the upstream
    default is :class:`NoopDecisionHistory` (empty). MUST be
    deterministic for a given ``(resource_id, limit)`` so the arbitration
    stays replayable: same audit log + same request => same decision.

    Async by contract because a real audit-log query is I/O-bound.
    """

    async def recent(self, resource_id: str, *, limit: int) -> Sequence[RecentDecision]:
        """Return up to ``limit`` most-recent decisions for ``resource_id``.

        Returns decisions in chronological order (oldest first) so a
        policy can walk them in either direction; an empty tuple is a
        valid answer and reproduces today's stateless behavior.
        """
        ...


class NoopDecisionHistory:
    """Upstream default - returns an empty history for every resource."""

    async def recent(self, resource_id: str, *, limit: int) -> Sequence[RecentDecision]:
        return ()


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    correlation_id: str
    winning_domain: str
    losing_domains: tuple[str, ...]
    reason: str
    # Multi-objective grounding (defaults keep legacy construction valid).
    objective_scores: dict[str, float] = field(default_factory=dict)
    margin: float = 0.0
    escalate_hil: bool = False


class Odin(Agent):
    """Wave-4 Odin: arbitration + portfolio outcome monitor."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        priority: tuple[str, ...] = _DEFAULT_PRIORITY,
        weights: dict[str, float] | None = None,
        weight_fn: Callable[[tuple[str, ...]], dict[str, float]] | None = None,
        hil_margin: float = 0.10,
        temporal_policy: TemporalPolicy | None = None,
        history: DecisionHistory | None = None,
        history_window: int = 10,
        vertical_precedence: CrossVerticalPrecedence | None = None,
    ) -> None:
        super().__init__(spec=_ODIN)
        self.bus = bus
        self._priority = priority
        self._arbiter = MultiObjectiveArbiter(
            priority=priority,
            weights=weights,
            weight_fn=weight_fn,
            hil_margin=hil_margin,
        )
        if history_window <= 0:
            raise ValueError(f"history_window MUST be positive (got {history_window!r})")
        # A configured policy without a history seam is a config error:
        # the policy would silently see an empty window and never fire.
        # Fail fast instead of pretending temporal fairness is enabled.
        if temporal_policy is not None and history is None:
            raise ValueError(
                "temporal_policy is set but no DecisionHistory was injected; "
                "bind NoopDecisionHistory explicitly to acknowledge intent"
            )
        self._temporal_policy = temporal_policy
        self._history: DecisionHistory = history or NoopDecisionHistory()
        self._history_window = history_window
        self._vertical_precedence = vertical_precedence
        # Conversational grounding for the arbitration and portfolio tools.
        # Last decision only (not a log): the durable record is Saga's audit
        # chain, and retaining more here would duplicate it without the
        # append-only guarantees.
        self._last_decision: ArbitrationDecision | None = None
        self._last_history_considered = 0
        self._verdicts_observed = 0
        self._verdict_outcomes: Counter[str] = Counter()

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.arbitration-request":
            await self.arbitrate(payload)
            return
        if topic == "object.verdict":
            self._observe_verdict(payload)

    def _observe_verdict(self, payload: dict[str, Any]) -> None:
        """Record one portfolio outcome observation.

        Odin subscribes ``object.verdict`` as the portfolio outcome
        monitor (``agent-pantheon.md`` 2). Observing is read-only
        bookkeeping: it counts what Forseti decided and never re-judges
        it. The outcome key space is bounded so a malformed producer
        cannot grow the counter without limit.
        """
        outcome = str(payload.get("risk_verdict") or payload.get("decision") or "unknown")
        if outcome not in _PORTFOLIO_OUTCOMES:
            outcome = "unknown"
        self._verdicts_observed += 1
        self._verdict_outcomes[outcome] += 1
        self.record_behavior(f"portfolio_outcome:{outcome}")

    async def arbitrate(self, request: dict[str, Any]) -> ArbitrationDecision:
        domains = tuple(str(d) for d in request.get("domains_in_conflict", ()))
        impacts = _coerce_impacts(request.get("impacts"))
        resource_id = str(request.get("resource_id", ""))
        # History lookup happens even when no policy is bound, so the
        # audit trail carries a consistent "policy considered N prior
        # decisions" annotation. Empty history is cheap.
        history: Sequence[RecentDecision] = ()
        if self._temporal_policy is not None and resource_id:
            history = await self._history.recent(resource_id, limit=self._history_window)
        precedence_winner = (
            self._vertical_precedence.winner(domains)
            if self._vertical_precedence is not None
            else None
        )
        if precedence_winner is None:
            outcome = self._arbiter.resolve(
                domains,
                impacts,
                history=history,
                policy=self._temporal_policy,
            )
        else:
            losers = tuple(domain for domain in domains if domain != precedence_winner)
            outcome = ArbitrationOutcome(
                winner=precedence_winner,
                losers=losers,
                objective_scores={domain: float(domain == precedence_winner) for domain in domains},
                margin=1.0,
                escalate_hil=False,
                reason="initial_vertical_precedence",
            )
        decision = ArbitrationDecision(
            correlation_id=str(request.get("correlation_id", "")),
            winning_domain=outcome.winner,
            losing_domains=outcome.losers,
            reason=outcome.reason,
            objective_scores=outcome.objective_scores,
            margin=outcome.margin,
            escalate_hil=outcome.escalate_hil,
        )
        self._last_decision = decision
        self._last_history_considered = len(history)
        if self.bus is not None:
            await self.bus.publish(
                "Odin",
                "object.arbitration-decision",
                {
                    "producer_principal": "Odin",
                    "correlation_id": decision.correlation_id,
                    "winning_domain": decision.winning_domain,
                    "losing_domains": list(decision.losing_domains),
                    "reason": decision.reason,
                    "objective_scores": decision.objective_scores,
                    "margin": decision.margin,
                    "escalate_hil": decision.escalate_hil,
                    # Grounding for the audit log: how many prior
                    # decisions the policy considered on this resource.
                    "history_considered": len(history),
                },
            )
        return decision

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Report whether any arbitration or portfolio evidence is retained.

        Odin's answers rest on accumulated runtime state: an arbitration
        it resolved, or verdicts it observed. Before either exists, the
        priority policy is the only thing it owns, so the turn composes
        the evidence-gap layer and the answer names what is missing
        instead of narrating the policy as if it were an outcome.
        """
        return self._last_decision is not None or self._verdicts_observed > 0

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        last = self._last_decision
        facts = {
            **capability_facts(self.spec),
            "priority_order": list(self._priority),
            "temporal_policy": self._temporal_policy.name if self._temporal_policy else None,
            "history_window": self._history_window,
            "arbitration_history_available": False,
            # Latest arbitration grounding. Present-but-``None`` when nothing
            # has been arbitrated yet, so the tool projection reports "no owned
            # data" instead of abstaining on a missing key or implying an
            # empty loser set is a real outcome.
            "winning_domain": last.winning_domain if last else None,
            "losing_domains": list(last.losing_domains) if last else None,
            "objective_scores": dict(last.objective_scores) if last else None,
            "margin": last.margin if last else None,
            "escalate_hil": last.escalate_hil if last else None,
            "history_considered": self._last_history_considered if last else None,
            "verdicts_observed": self._verdicts_observed,
            "verdict_outcomes": dict(self._verdict_outcomes),
        }
        if "history" in question.casefold():
            return IntrospectionResult(
                answer="No retained arbitration history is bound to this conversational port.",
                facts=facts,
            )
        policy_note = (
            f" with {self._temporal_policy.name} temporal fairness"
            if self._temporal_policy is not None
            else ""
        )
        answer = (
            "I arbitrate cross-vertical conflicts by weighted objective score over priority "
            f"({' > '.join(self._priority)}){policy_note}, "
            "escalating near-ties to HIL."
        )
        if last is not None:
            answer += (
                f" The last decision gave {last.winning_domain} the win "
                f"by a margin of {last.margin:.3f}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


def _coerce_impacts(raw: Any) -> dict[str, float] | None:
    """Coerce an untrusted ``impacts`` payload into ``{domain: float}``.

    A corrupt value (non-numeric, ``None``, wrong type) is preserved as
    ``NaN`` on that domain, NOT silently dropped. Dropping it would let
    the arbiter default that domain to a full-weight impact of ``1.0``
    and silently give it the win - a fail-open path. Preserving it as
    ``NaN`` triggers the arbiter's non-finite guard, which escalates the
    whole call to HIL (fail toward safety).

    A payload that is not a dict at all falls through to the priority-
    order fallback (``impacts=None``), which is the same behavior as no
    impacts being supplied.
    """
    if not isinstance(raw, dict):
        return None
    coerced: dict[str, float] = {}
    for key, value in raw.items():
        try:
            coerced[str(key)] = float(value)
        except (TypeError, ValueError):
            coerced[str(key)] = float("nan")
    return coerced or None


__all__ = [
    "Odin",
    "ArbitrationDecision",
    "DecisionHistory",
    "NoopDecisionHistory",
]
