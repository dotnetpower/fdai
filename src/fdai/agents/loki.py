"""Loki - Chaos (Wave 5 behavior).

Loki schedules chaos experiments with a bounded blast_radius and
NEVER auto-executes. Every proposed experiment routes through Forseti
and Var as an HIL action; Loki merely emits the proposal.

Blast-radius accounting is deterministic: no matter how many
proposals come in per unit time, the cumulative in-flight target count
is capped by :pyattr:`blast_radius_cap`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult, capability_facts
from fdai.agents._framework.pantheon import _LOKI

#: Cap on the retained proposal log. Loki appends one entry per proposal for
#: the process lifetime; the log is only read for recent-accepted diagnostics,
#: so a bounded ring is sufficient and stops an unbounded leak on a
#: long-running chaos scheduler.
_MAX_PROPOSALS = 1_000


@dataclass
class ChaosProposal:
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    accepted: bool
    reason: str


class Loki(Agent):
    """Wave-5 Loki: chaos scheduler with blast-radius cap."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        blast_radius_cap: int = 3,
    ) -> None:
        super().__init__(spec=_LOKI)
        self.bus = bus
        self._cap = blast_radius_cap
        self._in_flight_targets: set[str] = set()
        self.proposals: deque[ChaosProposal] = deque(maxlen=_MAX_PROPOSALS)

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    # ---- experiment scheduling ----------------------------------------

    async def propose_experiment(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
        correlation_id: str = "",
    ) -> ChaosProposal:
        # Enforce cap BEFORE emitting anything so a proposal storm does
        # not exceed the declared radius.
        available = self._cap - len(self._in_flight_targets)
        if available <= 0:
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="blast_radius_full",
            )
            self.proposals.append(proposal)
            return proposal
        selected = tuple(t for t in targets if t not in self._in_flight_targets)[:available]
        if not selected:
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="no_new_targets",
            )
            self.proposals.append(proposal)
            return proposal
        self._in_flight_targets.update(selected)
        proposal = ChaosProposal(
            experiment_id=experiment_id,
            action_type=action_type,
            targets=selected,
            accepted=True,
            reason="within_radius",
        )
        self.proposals.append(proposal)
        if self.bus is not None:
            await self.bus.publish(
                "Loki",
                "object.chaos-experiment",
                {
                    "producer_principal": "Loki",
                    "correlation_id": correlation_id or experiment_id,
                    "experiment_id": experiment_id,
                    "action_type": action_type,
                    "targets": list(selected),
                    "blast_radius_used": len(selected),
                },
            )
        return proposal

    def release_targets(self, targets: tuple[str, ...]) -> None:
        """Called after experiment completion (Wave 5 test helper)."""
        for t in targets:
            self._in_flight_targets.discard(t)

    # ---- conversational port -------------------------------------------

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        accepted = [p for p in self.proposals if p.accepted]
        facts = {
            **capability_facts(self.spec),
            "blast_radius_cap": self._cap,
            "in_flight_targets": sorted(self._in_flight_targets),
            "proposals_total": len(self.proposals),
            "proposals_accepted": len(accepted),
        }
        if not self.proposals:
            answer = (
                "No chaos experiments proposed yet; every experiment I raise is "
                f"HIL-gated with a blast-radius cap of {self._cap}."
            )
        else:
            answer = (
                f"{len(accepted)}/{len(self.proposals)} chaos proposal(s) accepted; "
                f"{len(self._in_flight_targets)}/{self._cap} blast-radius slot(s) in use."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Loki", "ChaosProposal"]
