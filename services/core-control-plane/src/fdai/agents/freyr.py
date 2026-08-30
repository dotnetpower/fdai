"""Freyr - Capacity (Wave 5 behavior).

Freyr samples utilization, projects forward via a light exponential
smoothing forecast, and exposes a sizing advisory hook.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from fdai.agents._framework.specialist_ingress import (
    CAPACITY_GRADUATION_EVENT,
    CAPACITY_SAMPLE_EVENT,
    parse_capacity_graduation_evidence,
    parse_capacity_sample,
)
from fdai.core.capacity import CapacityGraduationController

#: Hard cap on retained per-resource utilization samples. The EWMA forecast
#: lives in ``_smoothed``; ``_samples`` is only read for its last value, its
#: length (the >= 3 scale_down guard), and the introspection count - so
#: trimming older samples is behavior-preserving and bounds memory on a
#: long-lived capacity watcher.
_MAX_SAMPLES = 512
_MAX_COST_EVIDENCE = 512


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
        graduation_controller: CapacityGraduationController | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(spec=_FREYR)
        self.bus = bus
        self._alpha = smoothing_alpha
        self._up = scale_up_threshold
        self._down = scale_down_threshold
        self._smoothed: dict[str, float] = {}
        self._samples: dict[str, list[float]] = {}
        self._graduation_controller = graduation_controller
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._cost_evidence: dict[str, tuple[str, datetime]] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.cost-anomaly":
            self._retain_cost_evidence(payload)
            return
        if topic != "object.event":
            return
        if payload.get("event_type") == CAPACITY_GRADUATION_EVENT:
            await self._evaluate_graduation(payload)
            return
        if payload.get("event_type") != CAPACITY_SAMPLE_EVENT:
            return
        signal = parse_capacity_sample(payload)
        if signal is None:
            self.record_behavior("capacity_sample:invalid")
            return
        self.record_behavior("capacity_sample:accepted")
        await self.ingest_utilization(
            resource_id=signal.resource_id,
            utilization=signal.utilization,
            correlation_id=signal.correlation_id,
            observed_at=signal.observed_at,
        )

    async def _evaluate_graduation(self, payload: dict[str, Any]) -> None:
        if self._graduation_controller is None:
            self.record_behavior("capacity_graduation:disabled")
            return
        evidence = parse_capacity_graduation_evidence(payload)
        if evidence is None:
            self.record_behavior("capacity_graduation:invalid")
            return
        cost = self._cost_evidence.get(evidence.target_ref)
        if cost is not None:
            evidence = evidence.model_copy(
                update={
                    "cost_evidence_ref": cost[0],
                    "cost_observed_at": cost[1],
                }
            )
        recommendation = self._graduation_controller.evaluate(
            evidence,
            evaluated_at=self._clock(),
        )
        published = await self._publish_proposal(
            "object.capacity-graduation-recommendation",
            {
                **recommendation.model_dump(mode="json"),
                "correlation_id": evidence.correlation_id,
                "idempotency_key": recommendation.id,
                "resource_id": evidence.target_ref,
            },
        )
        self.record_behavior(
            "capacity_graduation:"
            + (recommendation.status.value if published else "publication_unavailable")
        )

    def _retain_cost_evidence(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Njord":
            self.record_behavior("capacity_graduation:invalid_cost_owner")
            return
        target_ref = str(payload.get("resource_id") or payload.get("target_ref") or "")
        evidence_ref = str(payload.get("evidence_ref") or payload.get("id") or "")
        raw_observed = payload.get("observed_at") or payload.get("detected_at")
        if not target_ref or not evidence_ref or not isinstance(raw_observed, str):
            self.record_behavior("capacity_graduation:invalid_cost_evidence")
            return
        try:
            observed_at = datetime.fromisoformat(raw_observed.replace("Z", "+00:00"))
        except ValueError:
            self.record_behavior("capacity_graduation:invalid_cost_evidence")
            return
        if observed_at.tzinfo is None:
            self.record_behavior("capacity_graduation:invalid_cost_evidence")
            return
        if len(self._cost_evidence) >= _MAX_COST_EVIDENCE and target_ref not in self._cost_evidence:
            self._cost_evidence.pop(next(iter(self._cost_evidence)))
        self._cost_evidence[target_ref] = (evidence_ref, observed_at.astimezone(UTC))
        self.record_behavior("capacity_graduation:cost_evidence_retained")

    async def ingest_utilization(
        self,
        *,
        resource_id: str,
        utilization: float,
        correlation_id: str = "",
        observed_at: str = "",
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
        if self.bus is not None:
            # Normalize the forecast into an impact magnitude in [0, 1] so
            # arbitration weighs the capacity signal by measured urgency, not
            # just priority. Smoothed forecast_util is already normalized; the
            # specialist owns this so Forseti does not have to know per-domain
            # metrics. Unlike a discretionary proposal (Njord's anomaly, a
            # rule candidate), the capacity forecast is a telemetry-cadence
            # refresh - one per ingested sample, bounded by the caller's
            # sampling rate - so it is NOT routed through the proposal rate
            # limiter (that would shed meaningful forecasts at random when the
            # window fills with routine samples).
            impact = max(0.0, min(1.0, smoothed))
            advice = self.sizing_advice(resource_id)
            action_arguments = (
                {
                    "target_resource_ref": resource_id,
                    "reason": "Capacity forecast crossed the reviewed scaling threshold.",
                }
                if advice.action in {"scale_up", "scale_down"}
                else None
            )
            await self.bus.publish(
                "Freyr",
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
                    "recommendation": advice.action,
                    "action_arguments": action_arguments,
                    "observed_at": observed_at,
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

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Capacity answers rest on utilization samples; thresholds alone are config."""
        return bool(self._samples)

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
