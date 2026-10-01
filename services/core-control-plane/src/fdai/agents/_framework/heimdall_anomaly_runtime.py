"""Heimdall owns independent observation, bounded anomaly episodes and evidence relays.

Admin notifications retain per-initiator/action deduplication; observation grants no authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, cast

from fdai.agents._framework.action_semantics import is_irreversible
from fdai.agents._framework.heimdall_alert_window import (
    MAX_TRACKED_KEYS as _MAX_TRACKED_KEYS,
)
from fdai.agents._framework.heimdall_alert_window import (
    anomaly_idempotency_key as _anomaly_idempotency_key,
)
from fdai.agents._framework.heimdall_alert_window import (
    event_window_time as _event_window_time,
)
from fdai.agents._framework.heimdall_alert_window import (
    incident_episode_id as _incident_episode_id,
)
from fdai.agents._framework.heimdall_helpers import (
    TRACE_CONTINUITY_REASONS as _TRACE_CONTINUITY_REASONS,
)
from fdai.agents._framework.heimdall_helpers import event_severity as _event_severity
from fdai.agents._framework.heimdall_helpers import evict_oldest as _evict_oldest
from fdai.agents._framework.heimdall_helpers import (
    trace_continuity_evidence as _trace_continuity_evidence,
)

AlerterHook = Callable[[dict[str, Any]], Awaitable[None]]
"""Var-provided hook that delivers the admin notification card."""

IncidentCandidateHook = Callable[[dict[str, Any]], Awaitable[bool]]
"""Composition hook returning whether the lifecycle accepted a candidate."""

ReadInvestigationHook = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]
"""Composition-provided read-only investigation responder."""

OperationalEvidenceHook = Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]
"""Composition-provided bounded evidence collector for one operational Event."""

_LOG = logging.getLogger(__name__)

_INCIDENT_CORRELATION_DISABLED = frozenset({"none", "disabled"})
_SEVERITY_RANK = {
    severity: rank for rank, severity in enumerate(("critical", "high", "medium", "low", "info"))
}
_DETECTION_READINESS_EVENT = "detection.readiness.observed"
_STATE_KEY = "pantheon/heimdall/sensing-state"
_EPISODE_PREFIX = "pantheon/heimdall/sensing-state/episodes/"
_READINESS_PREFIX = "pantheon/heimdall/sensing-state/readiness/"
_PENDING_READINESS_PREFIX = "pantheon/heimdall/sensing-state/readiness-pending/"
_PUBLICATION_PREFIX = "pantheon/heimdall/publications/"
_PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES = 8192
_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)
_PUBLICATION_CAS_ATTEMPTS = 8
_PUBLICATION_RECOVERY_LIMIT = 5_000
_PUBLICATION_MAINTENANCE_PAGE = 16
_RULE_VALIDATION_TIMEOUT_SECONDS = 5.0
_FULL_SNAPSHOT_LIMIT = 128
_MAX_KPI_SAMPLES = 512


def _kpi_measured(
    value: float,
    *,
    numerator: int | float,
    denominator: int | float,
    unit: str = "ratio",
) -> dict[str, Any]:
    return {
        "value": float(value),
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


def _kpi_unavailable(evidence_state: str, reason: str, *, unit: str = "ratio") -> dict[str, Any]:
    return {
        "value": None,
        "evidence_state": evidence_state,
        "reason": reason,
        "numerator": 0,
        "denominator": 0,
        "unit": unit,
    }


def _ratio_kpi(numerator: object, denominator: object, *, reason: str) -> dict[str, Any]:
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int | float)
        or not isinstance(denominator, int | float)
        or denominator <= 0
    ):
        return _kpi_unavailable("insufficient_sample", reason)
    return _kpi_measured(
        float(numerator) / float(denominator),
        numerator=numerator,
        denominator=denominator,
    )


def _mean_kpi(samples: deque[float], *, reason: str, unit: str) -> dict[str, Any]:
    if not samples:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    return _kpi_measured(
        sum(samples) / len(samples),
        numerator=len(samples),
        denominator=len(samples),
        unit=unit,
    )


class HeimdallAnomalyRuntimeMixin:
    """Behavior-preserving extracted runtime methods."""

    async def _maybe_emit_anomaly(self: Any, event: dict[str, Any]) -> None:
        resource_id = str(event.get("resource_id") or "")
        if not resource_id:
            self.record_behavior("anomaly_event:missing_resource")
            return
        event_type = str(event.get("event_type", "generic"))
        correlation_id = str(event.get("correlation_id") or "").strip()
        incident_correlation = (
            str(event.get("incident_correlation") or "correlate").strip().casefold()
        )
        time_basis, observed_at = _event_window_time(event, fallback=self._clock())
        episode_key = (
            resource_id,
            event_type,
            correlation_id,
            incident_correlation,
            time_basis,
        )
        history = self._episode_history(episode_key)
        self._dirty_episode_keys.add(episode_key)
        watermark = max(observed_at, history[-1][0] if history else observed_at)
        while history and watermark - history[0][0] > self._rate_window:
            history.popleft()
        if not history:
            self._incident_episode_ids.pop(episode_key, None)
            self._incident_episode_severities.pop(episode_key, None)
        if observed_at < watermark - self._rate_window:
            self.record_behavior("repeated_event_out_of_window")
            await self._persist_state()
            return
        evidence_key = str(event.get("idempotency_key") or event.get("event_id") or "").strip()
        if evidence_key and any(item[2] == evidence_key for item in history):
            self.record_behavior("repeated_event_duplicate")
            if len(history) < self._rate_threshold:
                await self._persist_state()
                return
        else:
            history.append(
                (
                    observed_at,
                    _event_severity(event),
                    evidence_key,
                )
            )
            history = deque(
                sorted(history, key=lambda item: (item[0], item[2])),
                maxlen=self._rate_threshold * 2,
            )
            self._recent_events[episode_key] = history
        if len(history) < self._rate_threshold:
            await self._persist_state()
            self.record_behavior("anomaly_window:collecting")
            return
        window_tail = list(history)[-self._rate_threshold :]
        if len(window_tail) == self._rate_threshold:
            severity = min(
                (event_severity for _, event_severity, _ in window_tail),
                key=_SEVERITY_RANK.__getitem__,
            )
            emitted_severity = self._incident_episode_severities.get(episode_key)
            if (
                emitted_severity is not None
                and _SEVERITY_RANK[severity] >= _SEVERITY_RANK[emitted_severity]
            ):
                self.record_behavior("anomaly_episode:suppressed_duplicate_severity")
                await self._persist_state()
                return
            if not correlation_id:
                self.record_behavior("incident_candidate_missing_correlation")
                self._drop_episode(episode_key)
                return
            incident_episode_id = self._incident_episode_ids.setdefault(
                episode_key,
                _incident_episode_id(episode_key, window_tail[0][2]),
            )
            anomaly = {
                "producer_principal": "Heimdall",
                "correlation_id": correlation_id,
                "idempotency_key": _anomaly_idempotency_key(
                    incident_episode_id,
                    severity,
                ),
                "resource_id": resource_id,
                "target_type": str(event.get("resource_type") or "unknown"),
                "event_type": event_type,
                "count_in_window": self._rate_threshold,
                "severity": severity,
                "incident_correlation": incident_correlation,
            }
            operational_evidence = await self._collect_operational_evidence(event)
            if operational_evidence:
                anomaly["operational_evidence"] = operational_evidence
            trace_continuity = _trace_continuity_evidence(event)
            if trace_continuity:
                anomaly["trace_continuity"] = trace_continuity
            if self.bus is not None:
                await self._publish_once("object.anomaly", anomaly)
            if self._incident_candidate_hook is None:
                self._drop_episode(episode_key)
                return
            if incident_correlation in _INCIDENT_CORRELATION_DISABLED:
                self.record_behavior("incident_candidate_correlation_disabled")
                self._drop_episode(episode_key)
                return
            if not correlation_id:
                self.record_behavior("incident_candidate_missing_correlation")
                self._drop_episode(episode_key)
                return
            if any(not evidence_key for _, _, evidence_key in window_tail):
                self.record_behavior("incident_candidate_missing_evidence")
                self._drop_episode(episode_key)
                return
            evidence_keys = tuple(dict.fromkeys(evidence_key for _, _, evidence_key in window_tail))
            reason_code = "repeated_event_threshold"
            trace_reason = trace_continuity.get("reason_code")
            if isinstance(trace_reason, str) and trace_reason in _TRACE_CONTINUITY_REASONS:
                reason_code = trace_reason
            candidate = {
                **anomaly,
                "reason_code": reason_code,
                "evidence_key": evidence_keys[-1],
                "evidence_keys": evidence_keys,
                "incident_episode_id": incident_episode_id,
            }
            try:
                accepted = await self._incident_candidate_hook(candidate)
            except Exception:  # noqa: BLE001 - retry on the next matching event
                self.record_behavior("incident_candidate_failed")
                _LOG.exception(
                    "incident_candidate_hook_failed",
                    extra={"correlation_id": anomaly["correlation_id"]},
                )
                return
            if accepted:
                self._incident_episode_severities[episode_key] = severity
                await self._persist_state()
            else:
                self._drop_episode(episode_key)
                await self._persist_state()
            self.record_behavior("incident_candidate" if accepted else "incident_candidate_held")

    async def _collect_operational_evidence(
        self: Any,
        event: dict[str, Any],
    ) -> Mapping[str, Any]:
        if self._operational_evidence_hook is None:
            return {}
        try:
            evidence = await self._operational_evidence_hook(event)
        except Exception:  # noqa: BLE001 - evidence loss cannot suppress the anomaly
            self.record_behavior("operational_evidence:provider_error")
            return {
                "observe.kubernetes.capacity": {
                    "status": "unavailable",
                    "reason": "provider_error",
                }
            }
        self.record_behavior(
            "operational_evidence:available" if evidence else "operational_evidence:not_applicable"
        )
        return dict(evidence)

    async def _maybe_classify_severity(self: Any, event: dict[str, Any]) -> str:
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
        await self._persist_state()
        return severity

    async def _maybe_send_admin_card(self: Any, event: dict[str, Any], severity: str) -> None:
        """Send an admin card, deduped by (initiator, action) within window."""
        initiator = str(event.get("initiator_principal", ""))
        action = str(event.get("attempted_action", ""))
        # Rate limit per user, per rolling hour (recovers when the window
        # rolls over - a monotonic counter would silence the user forever).
        if not self._reserve_alert_slot(initiator):
            await self._persist_state()
            return
        await self._persist_state()
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

    @asynccontextmanager
    async def _publication_lock(self: Any, publication_digest: str) -> AsyncIterator[None]:
        lock = self._lock_for_publication(publication_digest)
        self._publication_lock_refs[publication_digest] = (
            self._publication_lock_refs.get(publication_digest, 0) + 1
        )
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._publication_lock_refs.get(publication_digest, 1) - 1
            if remaining > 0:
                self._publication_lock_refs[publication_digest] = remaining
            else:
                self._publication_lock_refs.pop(publication_digest, None)
                self._publication_locks.pop(publication_digest, None)

    def _lock_for_publication(self: Any, publication_digest: str) -> asyncio.Lock:
        lock = self._publication_locks.get(publication_digest)
        if lock is None:
            lock = asyncio.Lock()
            self._publication_locks[publication_digest] = lock
        return cast(asyncio.Lock, lock)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ["HeimdallAnomalyRuntimeMixin"]
