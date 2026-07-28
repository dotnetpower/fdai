"""Heimdall - Observer (Wave 3 + Wave 6 behavior).

Heimdall detects anomalies from Event streams, correlates
SecurityEvents into severity classifications, and (Wave 6) delivers
admin notifications through a pluggable ``alerter_hook`` that Var
registers. Deduplication of admin cards uses a rolling window per
(initiator, action) pair.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
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
from fdai.agents._framework.specialist_ingress import SPECIALIST_EVENT_PREFIX
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.core.readiness import (
    AuthorityCeiling,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    DetectionReadinessSnapshot,
    reduce_detection_readiness,
)
from fdai.shared.contracts.models import ForecastOutcome

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
_INCIDENT_CORRELATION_DISABLED = frozenset({"none", "disabled"})
_SEVERITY_ALIASES = {
    "sev1": "critical",
    "sev2": "high",
    "sev3": "medium",
    "sev4": "low",
    "sev5": "info",
}
_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
_SEVERITY_RANK = {
    severity: rank for rank, severity in enumerate(("critical", "high", "medium", "low", "info"))
}
_MAX_FORECAST_PUBLICATION_ATTEMPTS = 5
_DETECTION_READINESS_EVENT = "detection.readiness.observed"


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
        forecast_clock: Callable[[], datetime] | None = None,
        forecast_evaluator: ForecastEpisodeEvaluator | None = None,
        forecast_closer: ForecastClosureCoordinator | None = None,
        forecast_store: ForecastEpisodeStore | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
    ) -> None:
        if rate_threshold < 1:
            raise ValueError("rate_threshold MUST be >= 1")
        if rate_window < 1:
            raise ValueError("rate_window MUST be >= 1")
        super().__init__(spec=_HEIMDALL)
        self.bus = bus
        self._rate_threshold = rate_threshold
        self._rate_window = rate_window
        self._recent_events: dict[str, deque[tuple[float, str, str, str, str]]] = {}
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
        self._forecast_clock = forecast_clock or (lambda: datetime.now(UTC))
        self._forecast_evaluator = forecast_evaluator
        self._forecast_closer = forecast_closer
        self._forecast_store = forecast_store
        self._action_semantics = action_semantics
        self._alert_windows: dict[str, tuple[float, int]] = {}
        self._detection_readiness: dict[str, dict[str, DetectionReadinessObservation]] = {}
        self._detection_readiness_pending: dict[
            tuple[str, str], dict[str, DetectionReadinessObservation]
        ] = {}

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

    async def publish_forecast_outcome(self, outcome: ForecastOutcome) -> bool:
        """Publish one schema-validated terminal forecast result."""
        if not isinstance(outcome, ForecastOutcome):
            raise TypeError("Heimdall forecast outcome MUST be a ForecastOutcome")
        self.record_behavior(f"forecast_outcome:{outcome.label.value}")
        if self.bus is None:
            return False
        await self.bus.publish(
            "Heimdall",
            "object.forecast-outcome",
            outcome.model_dump(mode="json"),
        )
        return True

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.event":
            if str(payload.get("event_type") or "").startswith(SPECIALIST_EVENT_PREFIX):
                self.record_behavior("specialist_signal:deferred")
                return
            if payload.get("event_type") == _DETECTION_READINESS_EVENT:
                await self._observe_detection_readiness(payload)
                return
            if payload.get("event_type") == "forecast.evaluation_due":
                await self._run_forecast_tick(payload)
                return
            if (
                payload.get("kind") == "document_ingestion"
                and payload.get("event_type") == "document.inspected"
            ):
                await self._emit_document_safety_signal(payload)
                return
            await self._maybe_emit_anomaly(payload)
        elif topic == "object.security-event":
            severity = await self._maybe_classify_severity(payload)
            if severity in ("high", "critical") and self._alerter_hook is not None:
                await self._maybe_send_admin_card(payload, severity)

    async def _observe_detection_readiness(self, event: dict[str, Any]) -> None:
        """Validate one probe fact and publish the agent-owned reduction."""
        resource_id = str(event.get("resource_id") or "")
        attributes = event.get("attributes")
        pass_id = str(attributes.get("pass_id") or "") if isinstance(attributes, dict) else ""
        if not resource_id or not pass_id or not isinstance(attributes, dict):
            self.record_behavior("detection_readiness:invalid")
            return
        try:
            observation = DetectionReadinessObservation.model_validate(
                {
                    "resource_ref": resource_id,
                    "dimension": attributes.get("dimension"),
                    "status": attributes.get("status"),
                    "observed_at": attributes.get("observed_at"),
                    "expires_at": attributes.get("expires_at"),
                    "source": attributes.get("source"),
                    "evidence_digest": attributes.get("evidence_digest"),
                    "detail_code": attributes.get("detail_code") or None,
                }
            )
        except ValueError:
            self.record_behavior("detection_readiness:invalid")
            return

        pending_key = (resource_id, pass_id)
        observations = self._detection_readiness_pending.setdefault(pending_key, {})
        _evict_oldest(self._detection_readiness_pending, _MAX_TRACKED_KEYS, keep=pending_key)
        observations[observation.dimension.value] = observation
        if len(observations) != len(DetectionReadinessDimension):
            self.record_behavior("detection_readiness:collecting")
            return
        self._detection_readiness[resource_id] = dict(observations)
        _evict_oldest(self._detection_readiness, _MAX_TRACKED_KEYS, keep=resource_id)
        del self._detection_readiness_pending[pending_key]
        snapshot = reduce_detection_readiness(
            tuple(observations.values()),
            resource_ref=resource_id,
            generated_at=self._forecast_clock(),
            deployment_ceiling=AuthorityCeiling.SHADOW,
        )
        await self._publish_detection_readiness(event, snapshot)

    async def _publish_detection_readiness(
        self,
        event: dict[str, Any],
        snapshot: DetectionReadinessSnapshot,
    ) -> None:
        material = {
            "resource_ref": snapshot.resource_ref,
            "decision": snapshot.decision.value,
            "authority_ceiling": snapshot.authority_ceiling.value,
            "observations": [
                {
                    "dimension": item.dimension.value,
                    "status": item.status.value,
                    "evidence_digest": item.evidence_digest,
                    "expires_at": item.expires_at.isoformat(),
                }
                for item in snapshot.observations
            ],
            "missing_dimensions": [item.value for item in snapshot.missing_dimensions],
            "stale_dimensions": [item.value for item in snapshot.stale_dimensions],
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload = {
            "producer_principal": "Heimdall",
            "kind": "detection_readiness",
            "event_type": "detection.readiness",
            "correlation_id": str(event.get("correlation_id") or f"readiness:{digest}"),
            "idempotency_key": f"detection-readiness:{digest}",
            "resource_id": snapshot.resource_ref,
            "target_type": "kubernetes-cluster",
            "decision": snapshot.decision.value,
            "authority_ceiling": snapshot.authority_ceiling.value,
            "generated_at": snapshot.generated_at.isoformat(),
            "observations": [item.model_dump(mode="json") for item in snapshot.observations],
            "missing_dimensions": [item.value for item in snapshot.missing_dimensions],
            "stale_dimensions": [item.value for item in snapshot.stale_dimensions],
        }
        self.record_behavior(f"detection_readiness:{snapshot.decision.value}")
        if self.bus is not None:
            await self.bus.publish("Heimdall", "object.drift", payload)

    async def _run_forecast_tick(self, payload: dict[str, Any]) -> None:
        identity_fields = (
            payload.get("event_id"),
            payload.get("idempotency_key"),
            payload.get("correlation_id"),
        )
        if payload.get("source") != "forecast-evaluation-scheduler" or any(
            not isinstance(value, str) or not value.startswith("forecast-evaluation:")
            for value in identity_fields
        ):
            self.record_behavior("forecast_tick:invalid")
            return
        if (
            self._forecast_evaluator is None
            or self._forecast_closer is None
            or self._forecast_store is None
        ):
            self.record_behavior("forecast_tick:unavailable")
            return
        now = self._forecast_clock()
        if now.tzinfo is None:
            raise ValueError("Heimdall forecast clock MUST be timezone-aware")
        evaluated = await self._forecast_evaluator.evaluate(now=now)
        closed = await self._forecast_closer.close_due(now=now)
        published = await self._publish_forecast_outbox(now=now)
        self.record_behavior("forecast_tick:completed")
        for _ in range(evaluated):
            self.record_behavior("forecast_episode:evaluated")
        for _ in range(closed):
            self.record_behavior("forecast_episode:closed")
        for _ in range(published):
            self.record_behavior("forecast_publication:published")

    async def _publish_forecast_outbox(self, *, now: datetime) -> int:
        if self._forecast_store is None or self.bus is None:
            return 0
        publications = await self._forecast_store.claim_publications(
            now=now,
            limit=100,
            lease_until=now + timedelta(seconds=60),
        )
        published = 0
        for publication in publications:
            try:
                publication_payload = dict(publication.payload)
                if publication.topic == "object.forecast-outcome":
                    publication_payload = ForecastOutcome.model_validate(
                        publication_payload
                    ).model_dump(mode="json")
                elif publication.topic != "object.forecast":
                    raise ValueError("forecast publication topic is unsupported")
                await self.bus.publish("Heimdall", publication.topic, publication_payload)
                await self._forecast_store.complete_publication(
                    publication.publication_id,
                    published_at=now,
                )
                published += 1
            except Exception as exc:
                error = type(exc).__name__
                if (
                    isinstance(exc, (TypeError, ValueError))
                    or publication.attempts >= _MAX_FORECAST_PUBLICATION_ATTEMPTS
                ):
                    await self._forecast_store.dead_letter_publication(
                        publication.publication_id,
                        failed_at=now,
                        error=error,
                    )
                    self.record_behavior("forecast_publication:dead_lettered")
                else:
                    await self._forecast_store.release_publication(
                        publication.publication_id,
                        available_at=now + timedelta(seconds=30),
                        error=error,
                    )
                    self.record_behavior("forecast_publication:retry")
                continue
        return published

    async def _emit_document_safety_signal(self, event: dict[str, Any]) -> None:
        """Normalize scanner/protection facts without making the verdict."""
        record = event.get("record")
        if not isinstance(record, dict):
            record = {}
        malware_verdict = str(record.get("malware_verdict") or "unavailable")
        protection_state = str(record.get("protection_state") or "unknown")
        failure_code = str(record.get("failure_code") or "")
        safety_status = (
            "clear"
            if malware_verdict == "clean"
            and not failure_code
            and protection_state in {"none", "labeled_unencrypted", "rights_managed_accessible"}
            else "blocked"
        )
        signal = {
            "producer_principal": "Heimdall",
            "kind": "document_ingestion",
            "stage": "protection_check",
            "correlation_id": str(event.get("correlation_id") or ""),
            "idempotency_key": str(event.get("idempotency_key") or ""),
            "resource_id": str(event.get("resource_id") or ""),
            "document_id": str(event.get("document_id") or ""),
            "upload_id": str(record.get("upload_id") or ""),
            "malware_verdict": malware_verdict,
            "protection_state": protection_state,
            "sensitivity_label": str(record.get("sensitivity_label") or ""),
            "purposes": list(record.get("purposes") or []),
            "initiator_principal": str(record.get("uploader_id") or ""),
            "failure_code": failure_code,
            "safety_status": safety_status,
        }
        self.record_behavior(f"document_safety:{safety_status}")
        if self.bus is not None:
            await self.bus.publish("Heimdall", "object.anomaly", signal)

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
        history.append(
            (
                now,
                str(event.get("event_type", "generic")),
                str(event.get("correlation_id") or "").strip(),
                _event_severity(event),
                str(event.get("idempotency_key") or event.get("event_id") or "").strip(),
            )
        )
        if len(history) < self._rate_threshold:
            return
        window_tail = list(history)[-self._rate_threshold :]
        event_types = {event_type for _, event_type, _, _, _ in window_tail}
        correlation_ids = {correlation_id for _, _, correlation_id, _, _ in window_tail}
        if len(event_types) == 1 and len(correlation_ids) == 1:
            incident_correlation = (
                str(event.get("incident_correlation") or "correlate").strip().casefold()
            )
            anomaly = {
                "producer_principal": "Heimdall",
                "correlation_id": event.get("correlation_id", ""),
                "resource_id": resource_id,
                "target_type": str(event.get("resource_type") or "unknown"),
                "event_type": window_tail[0][1],
                "count_in_window": self._rate_threshold,
                "severity": min(
                    (severity for _, _, _, severity, _ in window_tail),
                    key=_SEVERITY_RANK.__getitem__,
                ),
                "incident_correlation": incident_correlation,
            }
            history.clear()
            if self.bus is not None:
                await self.bus.publish("Heimdall", "object.anomaly", anomaly)
            if self._incident_candidate_hook is not None:
                if incident_correlation in _INCIDENT_CORRELATION_DISABLED:
                    self.record_behavior("incident_candidate_correlation_disabled")
                    return
                if not str(event.get("correlation_id") or "").strip():
                    self.record_behavior("incident_candidate_missing_correlation")
                    return
                if any(not evidence_key for _, _, _, _, evidence_key in window_tail):
                    self.record_behavior("incident_candidate_missing_evidence")
                    return
                evidence_keys = tuple(
                    dict.fromkeys(evidence_key for _, _, _, _, evidence_key in window_tail)
                )
                candidate = {
                    **anomaly,
                    "reason_code": "repeated_event_threshold",
                    "evidence_key": evidence_keys[-1],
                    "evidence_keys": evidence_keys,
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

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Observation answers rest on a populated window of signals.

        A bound read-investigation hook is its own evidence source, so it
        keeps the turn grounded even before the local window fills.
        """
        return bool(self._recent_events or self._security_recent or self._read_investigation_hook)

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
            "rate_window_seconds": self._rate_window,
            "forecast_evidence_available": False,
            "drift_evidence_available": False,
        }
        normalized_question = question.casefold()
        if "forecast" in normalized_question:
            return IntrospectionResult(
                answer="No retained forecast episode is bound to this conversational projection.",
                facts=facts,
            )
        if "drift" in normalized_question:
            return IntrospectionResult(
                answer="No retained drift finding is bound to this conversational projection.",
                facts=facts,
            )
        resources = mentioned(question, self._recent_events)
        if resources:
            rid = resources[0]
            history = list(self._recent_events[rid])
            event_types = sorted({event_type for _, event_type, _, _, _ in history})
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


def _event_severity(event: dict[str, Any]) -> str:
    attributes = event.get("attributes")
    attribute_severity = attributes.get("severity") if isinstance(attributes, dict) else None
    raw = str(event.get("severity") or event.get("severity_hint") or attribute_severity or "")
    normalized = raw.strip().casefold()
    aliased = _SEVERITY_ALIASES.get(normalized, normalized)
    return aliased if aliased in _SEVERITIES else "medium"


__all__ = [
    "Heimdall",
    "AlerterHook",
    "IncidentCandidateHook",
    "ReadInvestigationHook",
]
