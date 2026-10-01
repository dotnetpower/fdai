"""Heimdall owns independent observation, bounded anomaly episodes and evidence relays.

Admin notifications retain per-initiator/action deduplication; observation grants no authority.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Any

from fdai.agents._framework.heimdall_alert_window import (
    MAX_TRACKED_KEYS as _MAX_TRACKED_KEYS,
)
from fdai.agents._framework.heimdall_alert_window import EpisodeKey as _EpisodeKey
from fdai.agents._framework.heimdall_helpers import evict_oldest as _evict_oldest
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.readiness import (
    AuthorityCeiling,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    DetectionReadinessSnapshot,
    reduce_detection_readiness,
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


class HeimdallReadinessRuntimeMixin:
    """Behavior-preserving extracted runtime methods."""

    async def _persist_state(self: Any) -> None:
        if self._state_store is None:
            return
        compact_episode_mode = len(self._recent_events) > _FULL_SNAPSHOT_LIMIT
        compact_readiness_mode = (
            len(self._detection_readiness) + len(self._detection_readiness_pending)
            > _FULL_SNAPSHOT_LIMIT
        )
        for episode_key in tuple(self._dirty_episode_keys):
            history = self._recent_events.get(episode_key)
            if history is None:
                continue
            await self._state_store.write_state(
                f"{_EPISODE_PREFIX}{_digest(_encode_episode_key(episode_key))}",
                {
                    "schema_version": "1.0.0",
                    "revision": len(history),
                    "episode_key": _encode_episode_key(episode_key),
                    "history": [
                        [timestamp, severity, evidence_key]
                        for timestamp, severity, evidence_key in history
                    ],
                },
            )
        for resource in tuple(self._dirty_readiness_resources):
            observations = self._detection_readiness.get(resource)
            if observations is None:
                continue
            pass_order = self._detection_readiness_pass_order.get(resource)
            await self._state_store.write_state(
                f"{_READINESS_PREFIX}{_digest(resource)}",
                {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "resource_id": resource,
                    "observations": {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    },
                    "pass_order": (
                        [pass_order[0], pass_order[1].isoformat()]
                        if pass_order is not None
                        else None
                    ),
                },
            )
        for resource, pass_id in tuple(self._dirty_pending_readiness):
            observations = self._detection_readiness_pending.get((resource, pass_id))
            if observations is None:
                continue
            pending_identity = resource + "\0" + pass_id
            await self._state_store.write_state(
                f"{_PENDING_READINESS_PREFIX}{_digest(pending_identity)}",
                {
                    "schema_version": "1.0.0",
                    "revision": len(observations),
                    "resource_id": resource,
                    "pass_id": pass_id,
                    "observations": {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    },
                },
            )
        await self._state_store.write_state(
            _STATE_KEY,
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "recent_events": {}
                if compact_episode_mode
                else {
                    _encode_episode_key(key): [
                        [timestamp, severity, evidence_key]
                        for timestamp, severity, evidence_key in history
                    ]
                    for key, history in self._recent_events.items()
                },
                "incident_episode_ids": {
                    _encode_episode_key(key): value
                    for key, value in self._incident_episode_ids.items()
                },
                "incident_episode_severities": {
                    _encode_episode_key(key): value
                    for key, value in self._incident_episode_severities.items()
                },
                "security_recent": list(self._security_recent),
                "alert_windows": {
                    key: [start, count] for key, (start, count) in self._alert_windows.items()
                },
                "detection_readiness": {}
                if compact_readiness_mode
                else {
                    resource: {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    }
                    for resource, observations in self._detection_readiness.items()
                },
                "detection_readiness_pending": {}
                if compact_readiness_mode
                else {
                    f"{resource}\0{pass_id}": {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    }
                    for (
                        resource,
                        pass_id,
                    ), observations in self._detection_readiness_pending.items()
                },
                "detection_readiness_pass_order": {}
                if compact_readiness_mode
                else {
                    resource: [pass_id, observed_at.isoformat()]
                    for resource, (
                        pass_id,
                        observed_at,
                    ) in self._detection_readiness_pass_order.items()
                },
            },
        )
        self._dirty_episode_keys.clear()
        self._dirty_readiness_resources.clear()
        self._dirty_pending_readiness.clear()

    async def _observe_t2_proposer_health(self: Any, event: dict[str, Any]) -> None:
        """Reduce one sanitized proposer receipt without another model call."""

        attributes = event.get("attributes")
        if not isinstance(attributes, dict):
            self.record_behavior("t2_proposer:invalid")
            return
        recovered = (
            event.get("event_type") == "control_plane.t2_proposer_recovered"
            and attributes.get("status") == "succeeded"
            and attributes.get("recovered") is True
        )
        if recovered:
            self.record_behavior("t2_proposer:recovered")
            return
        terminal = attributes.get("terminal") is True and attributes.get("status") == "failed"
        if not terminal:
            self.record_behavior("t2_proposer:degraded")
            return
        correlation_id = str(event.get("correlation_id") or "")
        resource_id = str(event.get("resource_id") or "")
        evidence_key = str(event.get("idempotency_key") or event.get("event_id") or "")
        if not correlation_id or not resource_id or not evidence_key:
            self.record_behavior("t2_proposer:invalid")
            return
        preferred_route = str(attributes.get("preferred_route_ref") or "")
        if preferred_route == "legacy":
            preferred_route = "primary"
        if preferred_route not in {"primary", "secondary"}:
            self.record_behavior("t2_proposer:invalid_route_hint")
            return
        alternate_route = (
            "secondary"
            if preferred_route == "primary"
            else "primary"
            if preferred_route == "secondary"
            else ""
        )
        anomaly = {
            "producer_principal": "Heimdall",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "t2-proposer-anomaly",
                correlation_id,
                resource_id,
                evidence_key,
                attributes.get("failure_class"),
            ),
            "resource_id": resource_id,
            "target_type": "llm-endpoint",
            "event_type": "control_plane.t2_proposer_failure",
            "severity": "high",
            "incident_correlation": "correlate",
            "reason_code": "t2_proposer_candidates_exhausted",
            "evidence_key": evidence_key,
            "evidence_keys": [evidence_key],
            "failure_class": str(attributes.get("failure_class") or "provider_error"),
            "prior_route_ref": preferred_route,
            "alternate_route_ref": alternate_route,
        }
        self.record_behavior("t2_proposer:unavailable")
        if self.bus is not None:
            await self.bus.publish("Heimdall", "object.anomaly", anomaly)
        if self._incident_candidate_hook is None:
            self.record_behavior("incident_candidate_hook:unavailable")
            return
        try:
            accepted = await self._incident_candidate_hook(anomaly)
        except Exception:  # noqa: BLE001 - next receipt retries the durable candidate
            self.record_behavior("t2_proposer:incident_failed")
            return
        self.record_behavior(
            "t2_proposer:incident_opened" if accepted else "t2_proposer:incident_held"
        )

    async def _observe_detection_readiness(self: Any, event: dict[str, Any]) -> None:
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
        self._readiness_observed_dimensions += 1
        self._readiness_expected_dimensions += len(DetectionReadinessDimension)
        self._dirty_pending_readiness.add(pending_key)
        if len(observations) != len(DetectionReadinessDimension):
            await self._persist_state()
            self.record_behavior("detection_readiness:collecting")
            return
        latest_pass = self._detection_readiness_pass_order.get(resource_id)
        pass_observed_at = max(item.observed_at for item in observations.values())
        now = self._forecast_clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Heimdall forecast clock MUST be timezone-aware")
        stale_delay = max(
            0.0,
            (now - min(item.observed_at for item in observations.values())).total_seconds(),
        )
        self._stale_inventory_delays_seconds.append(stale_delay)
        if latest_pass is not None and pass_observed_at <= latest_pass[1]:
            self._detection_readiness_pending.pop(pending_key, None)
            await self._persist_state()
            self.record_behavior("detection_readiness:stale_pass")
            return
        self._detection_readiness[resource_id] = dict(observations)
        self._detection_readiness_pass_order[resource_id] = (pass_id, pass_observed_at)
        self._dirty_readiness_resources.add(resource_id)
        _evict_oldest(self._detection_readiness, _MAX_TRACKED_KEYS, keep=resource_id)
        del self._detection_readiness_pending[pending_key]
        snapshot = reduce_detection_readiness(
            tuple(observations.values()),
            resource_ref=resource_id,
            generated_at=self._forecast_clock(),
            deployment_ceiling=AuthorityCeiling.SHADOW,
        )
        await self._publish_detection_readiness(event, snapshot, pass_id=pass_id)
        await self._persist_state()

    async def _publish_detection_readiness(
        self: Any,
        event: dict[str, Any],
        snapshot: DetectionReadinessSnapshot,
        *,
        pass_id: str,
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
        generated_at = snapshot.generated_at.isoformat()
        idempotency_key = stable_idempotency_key(
            "detection-readiness",
            snapshot.resource_ref,
            pass_id,
            generated_at,
            digest,
        )
        payload = {
            "producer_principal": "Heimdall",
            "kind": "detection_readiness",
            "event_type": "detection.readiness",
            "correlation_id": str(event.get("correlation_id") or idempotency_key),
            "idempotency_key": idempotency_key,
            "resource_id": snapshot.resource_ref,
            "target_type": "kubernetes-cluster",
            "pass_id": pass_id,
            "content_digest": digest,
            "decision": snapshot.decision.value,
            "readiness_status": "stale" if snapshot.stale_dimensions else snapshot.decision.value,
            "authority_ceiling": snapshot.authority_ceiling.value,
            "generated_at": generated_at,
            "observations": [item.model_dump(mode="json") for item in snapshot.observations],
            "missing_dimensions": [item.value for item in snapshot.missing_dimensions],
            "stale_dimensions": [item.value for item in snapshot.stale_dimensions],
        }
        self.record_behavior(f"detection_readiness:{snapshot.decision.value}")
        if self.bus is not None:
            await self._publish_once("object.drift", payload)

    async def _emit_document_safety_signal(self: Any, event: dict[str, Any]) -> None:
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


def _encode_episode_key(key: _EpisodeKey) -> str:
    return json.dumps(key, ensure_ascii=True, separators=(",", ":"))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ["HeimdallReadinessRuntimeMixin"]
