"""Mimir - Rule Steward (Wave 2 behavior).

Mimir tracks rule shadow / enforce promotion. Wave 2 exposes a minimal
in-memory promotion tracker; the concrete rule catalog loader stays in
:mod:`fdai.rule_catalog`. Mimir's job here is the promotion state
machine and the RuleCandidate intake.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _MIMIR

#: Cap on retained rejected-candidate records. Quarantine holds candidates the
#: CandidateGuard REJECTED - i.e. attacker-controlled volume under a
#: candidate-poisoning attempt. An unbounded list would be a memory-exhaustion
#: DoS vector: a poisoning flood grows it without limit. The durable audit
#: trail is Saga's chain; this in-memory list is a bounded diagnostic ring.
_MAX_QUARANTINE = 5_000


@dataclass(frozen=True, slots=True)
class RulePromotion:
    rule_id: str
    state: str  # shadow | enforce | retired
    source: str  # handoff | override | manual | coherence
    updated_at: str | None


class Mimir(Agent):
    """Wave-2 Mimir: promotion state + candidate intake."""

    def __init__(self) -> None:
        super().__init__(spec=_MIMIR)
        self._promotions: dict[str, RulePromotion] = {}
        self._pending_candidates: list[dict[str, Any]] = []
        self._quarantined_candidates: deque[dict[str, Any]] = deque(maxlen=_MAX_QUARANTINE)
        self._guard = CandidateGuard()

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.rule-candidate":
            verdict = self._guard.inspect(payload)
            if verdict.accepted:
                self._pending_candidates.append(dict(payload))
            else:
                # Quarantine (not drop): the rejected candidate is kept with
                # its reason so the audit trail shows why the discovery loop
                # refused it (grounded-provenance MUST + poisoning defense).
                self._quarantined_candidates.append(
                    {**dict(payload), "quarantine_reason": verdict.reason}
                )

    def pending_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._pending_candidates)

    def quarantined_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._quarantined_candidates)

    def promote(
        self,
        rule_id: str,
        *,
        source: str,
        updated_at: str | None = None,
    ) -> RulePromotion:
        promo = RulePromotion(
            rule_id=rule_id, state="enforce", source=source, updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        self._pending_candidates = [
            c for c in self._pending_candidates if c.get("target_rule_id") != rule_id
        ]
        return promo

    def revoke(self, rule_id: str, *, updated_at: str | None = None) -> RulePromotion:
        promo = RulePromotion(
            rule_id=rule_id, state="retired", source="manual", updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        return promo

    def status(self, rule_id: str) -> RulePromotion | None:
        return self._promotions.get(rule_id)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_rules": capped_list(sorted(self._promotions)),
            "tracked_rules_count": len(self._promotions),
            "pending_candidates": len(self._pending_candidates),
            "quarantined_candidates": len(self._quarantined_candidates),
        }
        rules = mentioned(question, self._promotions)
        if rules:
            promo = self._promotions[rules[0]]
            facts.update({"rule_id": promo.rule_id, "state": promo.state, "source": promo.source})
            answer = f"Rule {promo.rule_id!r} is {promo.state} (source: {promo.source})."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Tracking {len(self._promotions)} rule promotion(s); "
            f"{len(self._pending_candidates)} candidate(s) pending the quality gate."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Mimir", "RulePromotion"]
