"""Njord - Cost / FinOps (Wave 5 behavior).

Njord ingests cost samples, detects anomalies against a rolling
baseline, and provides a cost-impact advisor hook that Forseti calls
during verdict composition.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _NJORD

#: Rolling baseline window (samples). The anomaly baseline only ever reads
#: the last :data:`_BASELINE_WINDOW` samples, so anything older is dead
#: weight.
_BASELINE_WINDOW = 30
#: Hard cap on retained per-scope samples. Bounds memory on a long-lived
#: cost watcher (one sample per billing tick, forever, per scope) while
#: keeping headroom above the baseline window for introspection reporting.
#: Older samples are never read, so trimming them is behavior-preserving.
_MAX_SAMPLES = 512


@dataclass(frozen=True, slots=True)
class CostEstimate:
    action_type: str
    monthly_delta_usd: float
    confidence: float


class Njord(Agent):
    """Wave-5 Njord: cost ingestion + anomaly + advisor."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        anomaly_ratio: float = 1.5,
        cost_table: dict[str, float] | None = None,
    ) -> None:
        super().__init__(spec=_NJORD)
        self.bus = bus
        self._anomaly_ratio = anomaly_ratio
        self._samples: dict[str, list[float]] = {}
        # Per-action monthly cost delta baseline (fork adapter replaces).
        self._cost_table = cost_table or {
            "ops.restart-service": 0.0,
            "remediate.disable-public-access": 0.0,
            "remediate.enable-encryption": 3.5,
            "remediate.resize_vm_up": 45.0,
            "remediate.resize_vm_down": -25.0,
        }

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    # ---- ingestion -----------------------------------------------------

    async def ingest_cost_sample(
        self,
        *,
        scope: str,
        amount_usd: float,
        correlation_id: str = "",
        resource_id: str | None = None,
    ) -> dict[str, Any] | None:
        history = self._samples.setdefault(scope, [])
        anomaly_payload: dict[str, Any] | None = None
        if len(history) >= 3:
            baseline = mean(history[-_BASELINE_WINDOW:])
            if baseline > 0 and amount_usd > baseline * self._anomaly_ratio:
                ratio = amount_usd / baseline
                # Normalize the overspend into an impact magnitude in [0, 1]
                # so arbitration weighs the cost signal by measured severity,
                # not just priority. `ratio - 1.0` = fractional overspend
                # (2x = 1.0 impact, 1.5x = 0.5, 1.1x = 0.1). The specialist
                # owns this normalization so Forseti does not have to know
                # per-domain metrics.
                impact = max(0.0, min(1.0, ratio - 1.0))
                anomaly_payload = {
                    "producer_principal": "Njord",
                    "correlation_id": correlation_id or scope,
                    "scope": scope,
                    "resource_id": resource_id or scope,
                    "amount_usd": amount_usd,
                    "baseline_usd": baseline,
                    "ratio": ratio,
                    "impact": impact,
                    # Cost pressure recommends shrinking to save spend; this
                    # can conflict with a capacity scale_up (Forseti arbitrates).
                    "recommendation": "scale_down",
                }
                # Advisory proposal: rate-limited per the agent's declared
                # rate_limits (agent-pantheon.md 7.9). The anomaly is still
                # returned to the caller when the bus publish is throttled.
                await self._publish_proposal("object.cost-anomaly", anomaly_payload)
        history.append(amount_usd)
        # Trim in place (keep the same list object) to the rolling cap - the
        # baseline only reads the tail, so dropping older samples changes no
        # decision but bounds memory on a long-lived watcher.
        if len(history) > _MAX_SAMPLES:
            del history[:-_MAX_SAMPLES]
        return anomaly_payload

    # ---- advisor hook --------------------------------------------------

    def cost_impact(self, action_type: str) -> CostEstimate:
        """Return a Forseti-consumable cost annotation for an action."""
        delta = self._cost_table.get(action_type, 0.0)
        confidence = 0.9 if action_type in self._cost_table else 0.3
        return CostEstimate(
            action_type=action_type,
            monthly_delta_usd=delta,
            confidence=confidence,
        )

    # ---- conversational port -------------------------------------------

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_scopes": capped_list(sorted(self._samples)),
            "tracked_scopes_count": len(self._samples),
            "anomaly_ratio": self._anomaly_ratio,
            "known_action_costs": dict(self._cost_table),
        }
        scopes = mentioned(question, self._samples)
        if scopes:
            scope = scopes[0]
            history = self._samples[scope]
            baseline = mean(history[-_BASELINE_WINDOW:]) if history else 0.0
            latest = history[-1] if history else 0.0
            facts.update(
                {
                    "scope": scope,
                    "sample_count": len(history),
                    "baseline_usd": baseline,
                    "latest_usd": latest,
                }
            )
            answer = (
                f"Scope {scope!r}: latest {latest:.2f} USD over {len(history)} "
                f"sample(s), baseline {baseline:.2f} USD."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        actions = mentioned(question, self._cost_table)
        if actions:
            estimate = self.cost_impact(actions[0])
            facts.update(
                {
                    "action_type": estimate.action_type,
                    "monthly_delta_usd": estimate.monthly_delta_usd,
                    "confidence": estimate.confidence,
                }
            )
            answer = (
                f"Cost impact of {estimate.action_type!r}: "
                f"{estimate.monthly_delta_usd:+.2f} USD/month "
                f"(confidence {estimate.confidence:.0%})."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        if not self._samples:
            answer = (
                "No cost samples ingested yet; I track per-scope spend and flag "
                f"anomalies above {self._anomaly_ratio:g}x baseline."
            )
        else:
            answer = (
                f"Tracking cost for {len(self._samples)} scope(s): "
                f"{', '.join(sorted(self._samples))}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Njord", "CostEstimate"]
