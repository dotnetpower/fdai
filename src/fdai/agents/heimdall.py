"""Heimdall - Observer (Wave 3 + Wave 6 behavior).

Heimdall detects anomalies from Event streams, correlates
SecurityEvents into severity classifications, and (Wave 6) delivers
admin notifications through a pluggable ``alerter_hook`` that Var
registers. Deduplication of admin cards uses a rolling window per
(initiator, action) pair.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from typing import Any

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog, is_irreversible
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

IncidentCandidateHook = Callable[[dict[str, Any]], Awaitable[None]]
"""Composition-provided hook that validates and opens an incident candidate."""

ReadInvestigationHook = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]
"""Composition-provided read-only investigation responder."""

_LOG = logging.getLogger(__name__)

#: The admin-card rate limit is per rolling hour. A limiter that never reset
#: would silence a user permanently after the first burst - so an attacker
#: could burn the initial quota, then operate with every later security
#: alert suppressed. The window makes the limit actually recover.
_ALERT_WINDOW_SECONDS = 3600.0

#: Cap on distinct keys retained in Heimdall's per-key maps (watched
#: resources, per-(initiator, action) counters, per-initiator alert budgets).
#: Each is keyed by an unbounded identifier (resource id / principal), so
#: without a cap a long-lived observer leaks one entry per identifier ever
#: seen. Oldest-first eviction bounds memory; an evicted resource simply
#: restarts its rate window on its next event.
_MAX_TRACKED_KEYS = 10_000


def _evict_oldest(mapping: dict[Any, Any], cap: int, *, keep: Any = None) -> None:
    """Bound ``mapping`` to ``cap`` entries, dropping oldest-first (insertion
    order), never evicting ``keep`` (the entry just written)."""
    while len(mapping) > cap:
        for key in mapping:
            if key != keep:
                del mapping[key]
                break
        else:  # only `keep` remains - nothing more to drop
            break


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
        incident_candidate_hook: IncidentCandidateHook | None = None,
        read_investigation_hook: ReadInvestigationHook | None = None,
        alert_rate_per_hour: int = 5,
        clock: Callable[[], float] | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
    ) -> None:
        super().__init__(spec=_HEIMDALL)
        self.bus = bus
        self._rate_threshold = rate_threshold
        self._rate_window = rate_window
        self._recent_events: dict[str, deque[tuple[float, str]]] = {}
        self._security_recent: deque[dict[str, Any]] = deque(maxlen=security_window_events)
        self._security_high_threshold = security_high_threshold
        self._alert_counters: Counter[tuple[str, str]] = Counter()
        self._alerter_hook = alerter_hook
        self._incident_candidate_hook = incident_candidate_hook
        self._read_investigation_hook = read_investigation_hook
        self._alert_rate_per_hour = alert_rate_per_hour
        # Per-initiator rolling-hour alert budget: (window_start, count).
        # Injected clock keeps the window deterministic under test; defaults
        # to a monotonic source so a wall-clock jump cannot reopen the budget.
        self._clock = clock or time.monotonic
        self._action_semantics = action_semantics
        self._alert_windows: dict[str, tuple[float, int]] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def register_alerter(self, hook: AlerterHook) -> None:
        self._alerter_hook = hook

    def register_incident_candidate(self, hook: IncidentCandidateHook) -> None:
        """Bind the composition-owned incident candidate validator/writer."""
        self._incident_candidate_hook = hook

    def register_read_investigation(self, hook: ReadInvestigationHook) -> None:
        """Bind a provider-neutral conversational read responder."""
        self._read_investigation_hook = hook

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
        _evict_oldest(self._recent_events, _MAX_TRACKED_KEYS, keep=resource_id)
        now = self._clock()
        while history and now - history[0][0] > self._rate_window:
            history.popleft()
        history.append((now, str(event.get("event_type", "generic"))))
        if len(history) < self._rate_threshold:
            return
        window_tail = [event_type for _, event_type in list(history)[-self._rate_threshold :]]
        if len(set(window_tail)) == 1:
            anomaly = {
                "producer_principal": "Heimdall",
                "correlation_id": event.get("correlation_id", ""),
                "resource_id": resource_id,
                "target_type": str(event.get("resource_type") or "unknown"),
                "event_type": window_tail[0],
                "count_in_window": self._rate_threshold,
                "severity": "medium",
            }
            history.clear()
            if self.bus is not None:
                await self.bus.publish("Heimdall", "object.anomaly", anomaly)
            if self._incident_candidate_hook is not None:
                evidence_key = str(event.get("idempotency_key") or event.get("event_id") or "")
                if not evidence_key:
                    self.record_behavior("incident_candidate_missing_evidence")
                    return
                candidate = {
                    **anomaly,
                    "reason_code": "repeated_event_threshold",
                    "evidence_key": evidence_key,
                }
                try:
                    await self._incident_candidate_hook(candidate)
                    self.record_behavior("incident_candidate")
                except Exception:  # noqa: BLE001 - anomaly remains authoritative
                    self.record_behavior("incident_candidate_failed")
                    _LOG.exception(
                        "incident_candidate_hook_failed",
                        extra={"correlation_id": anomaly["correlation_id"]},
                    )

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
        if hint == "critical" or is_irreversible(action, self._action_semantics):
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
        _evict_oldest(self._alert_counters, _MAX_TRACKED_KEYS, keep=(initiator, action))
        return severity

    def _reserve_alert_slot(self, initiator: str) -> bool:
        """Reserve one admin-card slot in the initiator's rolling-hour budget.

        Returns ``True`` and charges the budget when a slot is available;
        ``False`` when the initiator has spent its quota in the current
        window. The window resets once :data:`_ALERT_WINDOW_SECONDS` elapses
        since it opened, so the limit throttles a burst without silencing the
        user permanently.
        """
        now = self._clock()
        start, count = self._alert_windows.get(initiator, (now, 0))
        if now - start >= _ALERT_WINDOW_SECONDS:
            # Window rolled over -> start a fresh budget.
            start, count = now, 0
        if count >= self._alert_rate_per_hour:
            self._alert_windows[initiator] = (start, count)
            _evict_oldest(self._alert_windows, _MAX_TRACKED_KEYS, keep=initiator)
            return False
        self._alert_windows[initiator] = (start, count + 1)
        _evict_oldest(self._alert_windows, _MAX_TRACKED_KEYS, keep=initiator)
        return True

    async def _maybe_send_admin_card(self, event: dict[str, Any], severity: str) -> None:
        """Send an admin card, deduped by (initiator, action) within window."""
        initiator = str(event.get("initiator_principal", ""))
        action = str(event.get("attempted_action", ""))
        # Rate limit per user, per rolling hour (recovers when the window
        # rolls over - a monotonic counter would silence the user forever).
        if not self._reserve_alert_slot(initiator):
            return
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
        if self._read_investigation_hook is not None:
            investigation = await self._read_investigation_hook(question, context)
            if investigation is not None:
                answer = investigation.get("answer")
                facts = investigation.get("facts")
                if not isinstance(answer, str) or not isinstance(facts, dict):
                    raise ValueError("read investigation hook returned an invalid response")
                return IntrospectionResult(answer=answer, facts=facts)
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
            event_types = sorted({event_type for _, event_type in history})
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


__all__ = [
    "Heimdall",
    "AlerterHook",
    "IncidentCandidateHook",
    "ReadInvestigationHook",
]
