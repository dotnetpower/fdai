"""Forseti's product-profile boundary for learned patterns and predictions (#1541).

The default observation-first profile keeps every forecast and every prediction-fed capacity
arbitration advisory: Forseti publishes an ActionType-free Verdict and builds no decision options,
planning record, or kinetic proposal from it. Only the explicitly selected governed execution
add-on lets that input reach the existing rule-match, arbitration, risk, approval, and execution
gates, and a forecast that does not declare ``mode: enforce`` still cannot yield an enforcing
Verdict. Deterministic judgment of observed signals is unaffected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.advisory_verdicts import advisory_verdict
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.shared.contracts.models import Mode

#: Advice domains whose recommendation is a prediction rather than an observed finding.
PREDICTION_ADVICE_DOMAINS: frozenset[str] = frozenset({"capacity"})

_FORECAST_SOURCE = "forecast"
_CAPACITY_FORECAST_SOURCE = "capacity_forecast"
_CAPACITY_ACTIONS = {
    "scale_up": "ops.scale-out",
    "scale_down": "ops.scale-in",
}


class ForsetiLearnedOutputMixin:
    """Gate learned and predicted input on the explicit governed execution selection."""

    bus: PantheonBus | None
    _governed_execution_selected: bool
    _advisory_arbitrations: BoundedLruDict[str, dict[str, Any]]
    _arbitration_resources: BoundedLruDict[str, str]
    _pending_arbitration_principals: BoundedLruDict[str, dict[str, str]]
    _pending_change_assessments: BoundedLruDict[str, dict[str, Any]]
    _unresolved_arbitrations: BoundedLruDict[str, dict[str, Any]]

    if TYPE_CHECKING:

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        async def maybe_request_arbitration(
            self,
            event: dict[str, Any],
        ) -> dict[str, Any] | None: ...

        async def judge(
            self,
            event: dict[str, Any],
            *,
            source_mode: Mode | None = None,
        ) -> dict[str, Any] | None: ...

    async def _judge_forecast(self, forecast: dict[str, Any]) -> dict[str, Any] | None:
        """Judge one forecast under the selected product boundary.

        Without the add-on the forecast becomes advisory evidence only: no rule match,
        arbitration, or ActionType is derived from its fields. With the add-on the existing
        path runs with one deliberate restriction: an action Verdict that ``judge`` derives
        from a forecast lacking an exact ``mode: enforce`` is capped at ``shadow_only``.
        """
        if not self._governed_execution_selected:
            return await self._publish_learned_output_advisory(
                forecast,
                advisory_source=_FORECAST_SOURCE,
            )
        mode = Mode.ENFORCE if forecast.get("mode") == Mode.ENFORCE.value else Mode.SHADOW
        if await self.maybe_request_arbitration(forecast) is not None:
            return None
        return await self.judge(forecast, source_mode=mode)

    async def _judge_capacity_forecast(
        self,
        forecast: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Judge Freyr's capacity forecast without bypassing the learned-output gate."""

        recommendation = str(forecast.get("recommendation") or "")
        action_type = _CAPACITY_ACTIONS.get(recommendation)
        if action_type is None:
            return await self._publish_learned_output_advisory(
                forecast,
                advisory_source=_CAPACITY_FORECAST_SOURCE,
            )
        judged = dict(forecast)
        judged["action_type"] = action_type
        raw_arguments = forecast.get("action_arguments")
        if isinstance(raw_arguments, Mapping):
            judged["params"] = dict(raw_arguments)
        judged["event_type"] = "capacity_forecast_threshold"
        return await self._judge_forecast(judged)

    def _mark_advisory_arbitration(self, correlation_id: str, advice: Mapping[str, str]) -> bool:
        """Mark a default-profile arbitration fed by a prediction and report whether it is one.

        A marked arbitration still asks Odin to weigh the contending objectives, but Forseti
        builds no DecisionCase options for it, so no ActionType, planning record, or kinetic
        proposal can be derived from the prediction.
        """
        if self._governed_execution_selected or PREDICTION_ADVICE_DOMAINS.isdisjoint(advice):
            return False
        if self._advisory_arbitrations.get(correlation_id) is None:
            self._advisory_arbitrations.set(
                correlation_id,
                {"source": _CAPACITY_FORECAST_SOURCE, "published": False, "lock": asyncio.Lock()},
            )
        self.record_behavior("learned_output_advisory:arbitration_marked")
        return True

    async def _settle_advisory_arbitration(
        self,
        correlation_id: str,
        decision: Mapping[str, Any],
        *,
        outcome: str,
        grounding_extra: Mapping[str, Any] | None = None,
    ) -> bool:
        """Publish at most one ActionType-free Verdict for a marked arbitration.

        Returns ``False`` for an unmarked correlation so the caller keeps the existing path.
        Every outcome records its grounding in ``_unresolved_arbitrations`` exactly as
        ``_escalate_arbitration`` does: the advisory path builds no DecisionCase, and the
        existing path escalates without one, so a later observed signal on the same
        correlation is held from automatic execution in both profiles. A per-correlation lock
        spans the publication, so an Odin decision and a concurrent fail-closed closure publish
        one Verdict; a failed publication leaves the marker unset and stays retryable.
        """
        state = self._advisory_arbitrations.get(correlation_id)
        if state is None:
            return False
        async with state["lock"]:
            if state["published"] is True:
                self.record_behavior("learned_output_advisory:duplicate")
                return True
            grounding: dict[str, Any] = {
                "winning_domain": str(decision.get("winning_domain", "")),
                "losing_domains": [str(item) for item in decision.get("losing_domains") or []],
                "margin": decision.get("margin"),
            }
            if grounding_extra is not None:
                grounding.update(dict(grounding_extra))
            self._pending_change_assessments.pop(correlation_id, None)
            self._pending_arbitration_principals.pop(correlation_id, None)
            verdict = advisory_verdict(
                correlation_id=correlation_id,
                resource_id=self._arbitration_resources.get(correlation_id) or "",
                advisory_source=str(state["source"]),
                arbitration_outcome=outcome,
            )
            verdict["arbitration"] = {"outcome": outcome, **grounding}
            if self.bus is not None:
                await self.bus.publish("Forseti", "object.verdict", verdict)
            if self._unresolved_arbitrations.get(correlation_id) is None:
                self._unresolved_arbitrations.set(correlation_id, grounding)
            state["published"] = True
        self.record_behavior(f"learned_output_advisory:{state['source']}")
        return True

    async def _publish_learned_output_advisory(
        self,
        payload: Mapping[str, Any],
        *,
        advisory_source: str,
    ) -> dict[str, Any] | None:
        resource_id = str(payload.get("resource_id") or "")
        correlation_id = str(payload.get("correlation_id") or payload.get("idempotency_key") or "")
        if not resource_id or not correlation_id:
            self.record_behavior("learned_output_advisory:invalid_identity")
            return None
        verdict = advisory_verdict(
            correlation_id=correlation_id,
            resource_id=resource_id,
            advisory_source=advisory_source,
        )
        self.record_behavior(f"learned_output_advisory:{advisory_source}")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict


__all__ = ["PREDICTION_ADVICE_DOMAINS", "ForsetiLearnedOutputMixin"]
