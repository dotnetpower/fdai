"""Bound Heimdall episode identity, retention, and alert-rate state."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework.heimdall_helpers import evict_oldest

ALERT_WINDOW_SECONDS = 3600.0
MAX_TRACKED_KEYS = 10_000
MAX_EPISODES_PER_RESOURCE = 100
EPISODE_ID_PREFIX = "episode:"
EpisodeKey = tuple[str, str, str, str, str]


def incident_episode_id(
    episode_key: EpisodeKey,
    first_evidence_key: str,
) -> str:
    """Derive one stable, opaque identity for a bounded repeat episode."""

    canonical = json.dumps(
        (*episode_key, first_evidence_key),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"{EPISODE_ID_PREFIX}{hashlib.sha256(canonical.encode()).hexdigest()}"


def anomaly_idempotency_key(incident_episode_id: str, severity: str) -> str:
    """Derive a retry-stable key for one episode severity publication."""

    digest = hashlib.sha256(f"{incident_episode_id}\0{severity}".encode()).hexdigest()
    return f"anomaly:{digest}"


def event_window_time(event: Mapping[str, Any], *, fallback: float) -> tuple[str, float]:
    """Return a comparable event-time or arrival-time coordinate."""

    value = event.get("occurred_at")
    if value is None:
        return "arrival", fallback
    if isinstance(value, datetime):
        observed_at = value
    elif isinstance(value, str):
        try:
            observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("event occurred_at MUST be RFC 3339") from exc
    else:
        raise ValueError("event occurred_at MUST be RFC 3339")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("event occurred_at MUST be timezone-aware")
    return "event", observed_at.timestamp()


class HeimdallAlertWindowMixin:
    """Retain bounded episode histories and rolling alert budgets."""

    _rate_threshold: int
    _max_tracked_keys: int
    _max_episodes_per_resource: int
    _recent_events: dict[EpisodeKey, deque[tuple[float, str, str]]]
    _recent_episode_keys: dict[str, dict[EpisodeKey, None]]
    _incident_episode_ids: dict[EpisodeKey, str]
    _incident_episode_severities: dict[EpisodeKey, str]
    _clock: Callable[[], float]
    _alert_windows: dict[str, tuple[float, int]]
    _alert_rate_per_hour: int
    _alert_counters: Counter[tuple[str, str]]

    def _episode_history(
        self,
        episode_key: EpisodeKey,
    ) -> deque[tuple[float, str, str]]:
        existing = self._recent_events.get(episode_key)
        if existing is not None:
            return existing
        resource_id = episode_key[0]
        resource_episodes = self._recent_episode_keys.setdefault(resource_id, {})
        resource_episodes[episode_key] = None
        while len(resource_episodes) > self._max_episodes_per_resource:
            self._drop_episode(next(iter(resource_episodes)))
        history: deque[tuple[float, str, str]] = deque(maxlen=self._rate_threshold * 2)
        self._recent_events[episode_key] = history
        while len(self._recent_events) > self._max_tracked_keys:
            self._drop_episode(next(iter(self._recent_events)))
        return history

    def _drop_episode(self, episode_key: EpisodeKey) -> None:
        self._recent_events.pop(episode_key, None)
        self._incident_episode_ids.pop(episode_key, None)
        self._incident_episode_severities.pop(episode_key, None)
        resource_id = episode_key[0]
        resource_episodes = self._recent_episode_keys.get(resource_id)
        if resource_episodes is None:
            return
        resource_episodes.pop(episode_key, None)
        if not resource_episodes:
            self._recent_episode_keys.pop(resource_id, None)

    def _reserve_alert_slot(self, initiator: str) -> bool:
        """Reserve one admin-card slot in the initiator's rolling-hour budget."""

        now = self._clock()
        start, count = self._alert_windows.get(initiator, (now, 0))
        if now - start >= ALERT_WINDOW_SECONDS:
            start, count = now, 0
        if count >= self._alert_rate_per_hour:
            self._alert_windows[initiator] = (start, count)
            evict_oldest(self._alert_windows, self._max_tracked_keys, keep=initiator)
            return False
        self._alert_windows[initiator] = (start, count + 1)
        evict_oldest(self._alert_windows, self._max_tracked_keys, keep=initiator)
        return True

    def alert_count(self, initiator: str, action: str) -> int:
        """Return the retained count for one initiator and action."""

        return self._alert_counters[(initiator, action)]


__all__ = [
    "MAX_TRACKED_KEYS",
    "MAX_EPISODES_PER_RESOURCE",
    "EpisodeKey",
    "HeimdallAlertWindowMixin",
    "anomaly_idempotency_key",
    "event_window_time",
    "incident_episode_id",
]
