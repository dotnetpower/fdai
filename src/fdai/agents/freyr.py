"""Freyr - Capacity (Wave 5 behavior).

Freyr samples utilization, projects forward via a light exponential
smoothing forecast, and exposes a sizing advisory hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _FREYR

#: Hard cap on retained per-resource utilization samples. The EWMA forecast
#: lives in ``_smoothed``; ``_samples`` is only read for its last value, its
#: length (the >= 3 scale_down guard), and the introspection count - so
#: trimming older samples is behavior-preserving and bounds memory on a
#: long-lived capacity watcher.
_MAX_SAMPLES = 512


@dataclass(frozen=True, slots=True)
class SizingRecommendation:
    resource_id: str
    current_util: float
    forecast_util: float
    action: str  # scale_up | scale_down | hold


class Freyr(Agent):
    """Wave-5 Freyr: utilization forecast + sizing advisor."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        smoothing_alpha: float = 0.3,
        scale_up_threshold: float = 0.75,
        scale_down_threshold: float = 0.25,
    ) -> None:
        super().__init__(spec=_FREYR)
        self.bus = bus
        self._alpha = smoothing_alpha
        self._up = scale_up_threshold
        self._down = scale_down_threshold
        self._smoothed: dict[str, float] = {}
        self._samples: dict[str, list[float]] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def ingest_utilization(
        self,
        *,
        resource_id: str,
        utilization: float,
        correlation_id: str = "",
    ) -> None:
        prev = self._smoothed.get(resource_id, utilization)
        smoothed = self._alpha * utilization + (1 - self._alpha) * prev
        self._smoothed[resource_id] = smoothed
        history = self._samples.setdefault(resource_id, [])
        history.append(utilization)
        # Trim in place to the rolling cap - only the tail and the length are
        # read, so dropping older samples changes no decision but bounds
        # memory on a long-lived watcher.
        if len(history) > _MAX_SAMPLES:
            del history[:-_MAX_SAMPLES]
        # Normalize the forecast into an impact magnitude in [0, 1] so
        # arbitration weighs the capacity signal by measured urgency, not
        # just priority. Smoothed forecast_util is already normalized; the
        # specialist owns this so Forseti does not have to know per-domain
        # metrics. Advisory proposal: rate-limited per the agent's declared
        # rate_limits (agent-pantheon.md 7.9); _publish_proposal no-ops when
        # no bus is bound.
        impact = max(0.0, min(1.0, smoothed))
        await self._publish_proposal(
            "object.capacity-forecast",
            {
                "producer_principal": "Freyr",
                "correlation_id": correlation_id or resource_id,
                "resource_id": resource_id,
                "forecast_util": smoothed,
                "impact": impact,
                "recent_samples": len(self._samples[resource_id]),
                # Sizing action doubles as the arbitration recommendation
                # (scale_up under high utilization can conflict with a
                # cost-driven scale_down).
                "recommendation": self.sizing_advice(resource_id).action,
            },
        )

    def sizing_advice(self, resource_id: str) -> SizingRecommendation:
        samples = self._samples.get(resource_id)
        current = samples[-1] if samples else 0.0
        forecast = self._smoothed.get(resource_id, current)
        if forecast >= self._up:
            action = "scale_up"
        elif forecast <= self._down and len(self._samples.get(resource_id, [])) >= 3:
            action = "scale_down"
        else:
            action = "hold"
        return SizingRecommendation(
            resource_id=resource_id,
            current_util=current,
            forecast_util=forecast,
            action=action,
        )

    # ---- conversational port -------------------------------------------

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_resources": capped_list(sorted(self._samples)),
            "tracked_resources_count": len(self._samples),
            "scale_up_threshold": self._up,
            "scale_down_threshold": self._down,
        }
        resources = mentioned(question, self._samples)
        if resources:
            rid = resources[0]
            advice = self.sizing_advice(rid)
            facts.update(
                {
                    "resource_id": rid,
                    "current_util": advice.current_util,
                    "forecast_util": advice.forecast_util,
                    "recommendation": advice.action,
                }
            )
            answer = (
                f"Resource {rid!r}: current util {advice.current_util:.0%}, "
                f"forecast {advice.forecast_util:.0%} -> recommend {advice.action}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        if not self._samples:
            answer = (
                "No utilization samples yet; I forecast per-resource capacity and advise sizing."
            )
        else:
            answer = (
                f"Tracking capacity for {len(self._samples)} resource(s): "
                f"{', '.join(sorted(self._samples))}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Freyr", "SizingRecommendation"]
