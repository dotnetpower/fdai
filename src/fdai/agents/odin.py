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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fdai.agents.arbitration import (
    _DEFAULT_PRIORITY,
    MultiObjectiveArbiter,
    RecentDecision,
    TemporalPolicy,
)
from fdai.agents.base import Agent
from fdai.agents.bus import PantheonBus
from fdai.agents.introspection import IntrospectionResult, capability_facts
from fdai.agents.pantheon import _ODIN


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
        hil_margin: float = 0.10,
        temporal_policy: TemporalPolicy | None = None,
        history: DecisionHistory | None = None,
        history_window: int = 10,
    ) -> None:
        super().__init__(spec=_ODIN)
        self.bus = bus
        self._priority = priority
        self._arbiter = MultiObjectiveArbiter(
            priority=priority,
            weights=weights,
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

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.arbitration-request":
            return
        await self.arbitrate(payload)

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
        outcome = self._arbiter.resolve(
            domains,
            impacts,
            history=history,
            policy=self._temporal_policy,
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

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "priority_order": list(self._priority),
            "temporal_policy": self._temporal_policy.name if self._temporal_policy else None,
            "history_window": self._history_window,
        }
        policy_note = (
            f" with {self._temporal_policy.name} temporal fairness"
            if self._temporal_policy is not None
            else ""
        )
        answer = (
            "I arbitrate cross-vertical conflicts by priority "
            f"({' > '.join(self._priority)}){policy_note}, "
            "escalating near-ties to HIL."
        )
        return IntrospectionResult(answer=answer, facts=facts)


def _coerce_impacts(raw: Any) -> dict[str, float] | None:
    """Coerce an untrusted ``impacts`` payload into ``{domain: float}``.

    Non-numeric or missing values are dropped so a malformed signal
    degrades to the priority-order fallback rather than raising.
    """
    if not isinstance(raw, dict):
        return None
    coerced: dict[str, float] = {}
    for key, value in raw.items():
        try:
            coerced[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return coerced or None


__all__ = [
    "Odin",
    "ArbitrationDecision",
    "DecisionHistory",
    "NoopDecisionHistory",
]
