"""Heimdall owns independent observation, bounded anomaly episodes and evidence relays.

Admin notifications retain per-initiator/action deduplication; observation grants no authority.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai.agents._framework.heimdall_alert_window import (
    MAX_TRACKED_KEYS as _MAX_TRACKED_KEYS,
)
from fdai.agents._framework.heimdall_alert_window import EpisodeKey as _EpisodeKey
from fdai.core.readiness import (
    DetectionReadinessObservation,
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


class HeimdallStateRecoveryMixin:
    """Behavior-preserving extracted runtime methods."""

    async def rehydrate(self: Any) -> int:
        """Restore restart-sensitive sensing windows and duplicate fences."""
        if self._state_store is None:
            return 0
        record = await self._state_store.read_state(_STATE_KEY)
        if record is None:
            return 0
        restored = 0
        self._recent_events.clear()
        self._recent_episode_keys.clear()
        episode_rows, _episode_total = await self._state_store.read_state_page(
            _EPISODE_PREFIX,
            limit=_MAX_TRACKED_KEYS,
        )
        for episode_record in reversed(episode_rows):
            episode_key = _decode_episode_key(str(episode_record.get("episode_key") or ""))
            raw_history = episode_record.get("history")
            if episode_key is None or not isinstance(raw_history, list):
                continue
            legacy_history: deque[tuple[float, str, str]] = deque(maxlen=self._rate_threshold * 2)
            for item in raw_history:
                if (
                    isinstance(item, list)
                    and len(item) == 3
                    and isinstance(item[0], int | float)
                    and isinstance(item[1], str)
                    and isinstance(item[2], str)
                ):
                    legacy_history.append((float(item[0]), item[1], item[2]))
            self._recent_events[episode_key] = legacy_history
            self._recent_episode_keys.setdefault(episode_key[0], {})[episode_key] = None
            restored += 1
        for raw_key, raw_history in dict(record.get("recent_events") or {}).items():
            if self._recent_events:
                break
            episode_key = _decode_episode_key(raw_key)
            if episode_key is None or not isinstance(raw_history, list):
                continue
            history: deque[tuple[float, str, str]] = deque(maxlen=self._rate_threshold * 2)
            for item in raw_history:
                if (
                    isinstance(item, list)
                    and len(item) == 3
                    and isinstance(item[0], int | float)
                    and isinstance(item[1], str)
                    and isinstance(item[2], str)
                ):
                    history.append((float(item[0]), item[1], item[2]))
            self._recent_events[episode_key] = history
            self._recent_episode_keys.setdefault(episode_key[0], {})[episode_key] = None
            restored += 1
        self._incident_episode_ids = {
            key: value
            for raw_key, value in dict(record.get("incident_episode_ids") or {}).items()
            if (key := _decode_episode_key(raw_key)) is not None and isinstance(value, str)
        }
        self._incident_episode_severities = {
            key: value
            for raw_key, value in dict(record.get("incident_episode_severities") or {}).items()
            if (key := _decode_episode_key(raw_key)) is not None and isinstance(value, str)
        }
        self._security_recent = deque(
            [item for item in list(record.get("security_recent") or []) if isinstance(item, dict)],
            maxlen=self._security_recent.maxlen,
        )
        self._alert_windows = {
            str(key): (float(value[0]), int(value[1]))
            for key, value in dict(record.get("alert_windows") or {}).items()
            if isinstance(value, list) and len(value) == 2
        }
        self._detection_readiness = _decode_readiness_map(record.get("detection_readiness"))
        readiness_rows, _readiness_total = await self._state_store.read_state_page(
            _READINESS_PREFIX,
            limit=_MAX_TRACKED_KEYS,
        )
        for readiness_record in reversed(readiness_rows):
            resource = str(readiness_record.get("resource_id") or "")
            observations = _decode_readiness_map(
                {resource: readiness_record.get("observations")}
            ).get(resource)
            pass_order = readiness_record.get("pass_order")
            if resource and observations is not None:
                self._detection_readiness[resource] = observations
                if isinstance(pass_order, list) and len(pass_order) == 2:
                    self._detection_readiness_pass_order[resource] = (
                        str(pass_order[0]),
                        datetime.fromisoformat(str(pass_order[1])),
                    )
        self._detection_readiness_pending = _decode_pending_readiness(
            record.get("detection_readiness_pending")
        )
        pending_rows, _pending_total = await self._state_store.read_state_page(
            _PENDING_READINESS_PREFIX,
            limit=_MAX_TRACKED_KEYS,
        )
        for pending_record in reversed(pending_rows):
            resource = str(pending_record.get("resource_id") or "")
            pass_id = str(pending_record.get("pass_id") or "")
            observations = _decode_pending_readiness(
                {f"{resource}\0{pass_id}": pending_record.get("observations")}
            ).get((resource, pass_id))
            if resource and pass_id and observations is not None:
                self._detection_readiness_pending[(resource, pass_id)] = observations
        self._detection_readiness_pass_order = {
            str(resource): (str(value[0]), datetime.fromisoformat(str(value[1])))
            for resource, value in dict(record.get("detection_readiness_pass_order") or {}).items()
            if isinstance(value, list) and len(value) == 2
        }
        return restored


def _decode_episode_key(value: object) -> _EpisodeKey | None:
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except ValueError:
        return None
    if (
        isinstance(decoded, list)
        and len(decoded) == 5
        and all(isinstance(item, str) for item in decoded)
    ):
        return (decoded[0], decoded[1], decoded[2], decoded[3], decoded[4])
    return None


def _decode_readiness_map(value: object) -> dict[str, dict[str, DetectionReadinessObservation]]:
    if not isinstance(value, Mapping):
        return {}
    restored: dict[str, dict[str, DetectionReadinessObservation]] = {}
    for resource, raw_observations in value.items():
        if not isinstance(resource, str) or not isinstance(raw_observations, Mapping):
            continue
        observations: dict[str, DetectionReadinessObservation] = {}
        for dimension, raw_observation in raw_observations.items():
            if not isinstance(dimension, str) or not isinstance(raw_observation, Mapping):
                continue
            try:
                observations[dimension] = DetectionReadinessObservation.model_validate(
                    raw_observation
                )
            except ValueError:
                continue
        if observations:
            restored[resource] = observations
    return restored


def _decode_pending_readiness(
    value: object,
) -> dict[tuple[str, str], dict[str, DetectionReadinessObservation]]:
    if not isinstance(value, Mapping):
        return {}
    restored: dict[tuple[str, str], dict[str, DetectionReadinessObservation]] = {}
    for raw_key, raw_observations in value.items():
        if not isinstance(raw_key, str) or "\0" not in raw_key:
            continue
        resource, pass_id = raw_key.split("\0", 1)
        decoded = _decode_readiness_map({resource: raw_observations}).get(resource)
        if decoded:
            restored[(resource, pass_id)] = decoded
    return restored


__all__ = ["HeimdallStateRecoveryMixin"]
