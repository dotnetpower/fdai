"""Heimdall - Observer (Wave 3 + Wave 6 behavior).

Heimdall detects anomalies from Event streams, correlates
SecurityEvents into severity classifications, and (Wave 6) delivers
admin notifications through a pluggable ``alerter_hook`` that Var
registers. Deduplication of admin cards uses a rolling window per
(initiator, action) pair.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Awaitable, Callable
from typing import Any

from fdai.agents._framework.action_semantics import is_irreversible
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _HEIMDALL

AlerterHook = Callable[[dict[str, Any]], Awaitable[None]]
"""Var-provided hook that delivers the admin notification card."""


class Heimdall(Agent):
    """Wave-3 anomaly detection + Wave 6 security correlator."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rate_threshold: int = 5,
        rate_window: int = 300,
        security_high_threshold: int = 5,
        security_window_events: int = 100,
        alerter_hook: AlerterHook | None = None,
        alert_rate_per_hour: int = 5,
    ) -> None:
        super().__init__(spec=_HEIMDALL)
        self.bus = bus
        self._rate_threshold = rate_threshold
        self._rate_window = rate_window
        self._recent_events: dict[str, deque[str]] = {}
        self._security_recent: deque[dict[str, Any]] = deque(maxlen=security_window_events)
        self._security_high_threshold = security_high_threshold
        self._alert_counters: Counter[tuple[str, str]] = Counter()
        self._alerter_hook = alerter_hook
        self._alert_rate_per_hour = alert_rate_per_hour
        self._alerts_sent_per_user: Counter[str] = Counter()

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def register_alerter(self, hook: AlerterHook) -> None:
        self._alerter_hook = hook

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.event":
            await self._maybe_emit_anomaly(payload)
        elif topic == "object.security-event":
            severity = await self._maybe_classify_severity(payload)
            if severity in ("high", "critical") and self._alerter_hook is not None:
                await self._maybe_send_admin_card(payload, severity)

    async def _maybe_emit_anomaly(self, event: dict[str, Any]) -> None:
        resource_id = str(event.get("resource_id") or "")
        if not resource_id:
            return
        history = self._recent_events.setdefault(
            resource_id, deque(maxlen=self._rate_threshold * 2)
        )
        history.append(str(event.get("event_type", "generic")))
        if len(history) < self._rate_threshold:
            return
        window_tail = list(history)[-self._rate_threshold :]
        if len(set(window_tail)) == 1 and self.bus is not None:
            anomaly = {
                "producer_principal": "Heimdall",
                "correlation_id": event.get("correlation_id", ""),
                "resource_id": resource_id,
                "event_type": window_tail[0],
                "count_in_window": self._rate_threshold,
                "severity": "medium",
            }
            await self.bus.publish("Heimdall", "object.anomaly", anomaly)
            history.clear()

    async def _maybe_classify_severity(self, event: dict[str, Any]) -> str:
        self._security_recent.append(event)
        initiator = str(event.get("initiator_principal", ""))
        action = str(event.get("attempted_action", ""))
        hint = str(event.get("severity_hint", "medium"))

        matches = sum(
            1
            for e in self._security_recent
            if e.get("initiator_principal") == initiator and e.get("attempted_action") == action
        )
        severity: str
        if hint == "critical" or is_irreversible(action):
            severity = "high"
        elif matches >= self._security_high_threshold:
            severity = "high"
        elif matches >= 3:
            severity = "medium"
        else:
            severity = "low"
        distinct_actions = len(
            {
                e.get("attempted_action")
                for e in self._security_recent
                if e.get("initiator_principal") == initiator
            }
        )
        if distinct_actions >= 3:
            severity = "critical"
        self._alert_counters[(initiator, action)] += 1
        return severity

    async def _maybe_send_admin_card(self, event: dict[str, Any], severity: str) -> None:
        """Send an admin card, deduped by (initiator, action) within window."""
        initiator = str(event.get("initiator_principal", ""))
        action = str(event.get("attempted_action", ""))
        # Rate limit per user.
        if self._alerts_sent_per_user[initiator] >= self._alert_rate_per_hour:
            return
        self._alerts_sent_per_user[initiator] += 1
        # Dedup: send one card per (initiator, action); repeat becomes
        # counter increment on the last card (handled by Var adapter).
        payload = {
            "producer_principal": "Var",
            "correlation_id": event.get("correlation_id", ""),
            "severity": severity,
            "initiator_principal": initiator,
            "attempted_action": action,
            "counter": self._alert_counters[(initiator, action)],
        }
        if self._alerter_hook is None:
            return
        await self._alerter_hook(payload)

    def alert_count(self, initiator: str, action: str) -> int:
        return self._alert_counters[(initiator, action)]

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "watched_resources": capped_list(sorted(self._recent_events)),
            "watched_resources_count": len(self._recent_events),
            "security_events_window": len(self._security_recent),
            "rate_threshold": self._rate_threshold,
        }
        resources = mentioned(question, self._recent_events)
        if resources:
            rid = resources[0]
            history = list(self._recent_events[rid])
            event_types = sorted(set(history))
            facts.update(
                {
                    "resource_id": rid,
                    "recent_event_count": len(history),
                    "recent_event_types": event_types,
                }
            )
            answer = (
                f"Resource {rid!r}: {len(history)} recent event(s), "
                f"type(s): {', '.join(event_types) or 'none'}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Watching {len(self._recent_events)} resource(s); "
            f"{len(self._security_recent)} security event(s) in window."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Heimdall", "AlerterHook"]
