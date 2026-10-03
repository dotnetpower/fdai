"""Capacity sampling and persistence mixin for Freyr."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.freyr_constants import (
    _ACCEPTED_PREFIX,
    _COST_EVIDENCE_MAX_AGE,
    _COST_PREFIX,
    _MAX_COST_EVIDENCE,
    _MAX_RETAINED_IDENTIFIER_CHARS,
    _MAX_TRACKED_RESOURCES,
    _RESOURCE_PREFIX,
)
from fdai.agents._framework.specialist_ingress import parse_capacity_graduation_evidence
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.capacity import CapacityGraduationController
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus

_MAX_SAMPLES = 512


@dataclass(frozen=True, slots=True)
class SizingRecommendation:
    resource_id: str
    current_util: float
    forecast_util: float
    action: str  # scale_up | scale_down | hold


class FreyrCapacityRuntimeMixin:
    """Retain capacity samples and produce advisory forecasts."""

    _state_store: StateStore | None
    _smoothed: BoundedLruDict[str, float]
    _samples: BoundedLruDict[str, list[float]]
    _latest_observed_at: dict[str, datetime]
    _accepted_sample_keys: BoundedLruSet[str]
    _cost_evidence: OrderedDict[str, tuple[str, datetime, str]]
    _graduation_controller: CapacityGraduationController | None
    _clock: Callable[[], datetime]
    _cost_evidence_lock: asyncio.Lock
    _alpha: float
    bus: PantheonBus | None
    _source_time_missing_samples: int
    _resource_lock_refs: dict[str, int]
    _resource_locks: dict[str, asyncio.Lock]
    _up: float
    _down: float

    if TYPE_CHECKING:

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        async def _publish_proposal(self, topic: str, payload: dict[str, Any]) -> bool: ...

    async def rehydrate(self) -> int:
        """Restore forecast smoothing, sample tails, duplicate fences, and cost evidence."""
        if self._state_store is None:
            return 0
        restored = 0
        for record in await self._state_store.read_states(
            _RESOURCE_PREFIX,
            limit=_MAX_TRACKED_RESOURCES,
        ):
            resource_id = str(record.get("resource_id") or "")
            smoothed = record.get("smoothed")
            samples = record.get("samples")
            latest = _parse_observed_at(str(record.get("latest_observed_at") or ""))
            if (
                resource_id
                and isinstance(smoothed, int | float)
                and isinstance(samples, list)
                and latest is not None
            ):
                values = [float(item) for item in samples if isinstance(item, int | float)]
                self._smoothed.set(resource_id, float(smoothed))
                self._samples.set(resource_id, values[-_MAX_SAMPLES:])
                self._latest_observed_at[resource_id] = latest
                restored += 1
        for record in await self._state_store.read_states(
            _ACCEPTED_PREFIX,
            limit=_MAX_TRACKED_RESOURCES * 4,
        ):
            sample_key = str(record.get("sample_key") or "")
            if sample_key:
                self._accepted_sample_keys.add(sample_key)
        for record in await self._state_store.read_states(_COST_PREFIX, limit=_MAX_COST_EVIDENCE):
            target_ref = str(record.get("target_ref") or "")
            evidence_ref = str(record.get("evidence_ref") or "")
            correlation_id = str(record.get("correlation_id") or "")
            observed_at = _parse_observed_at(str(record.get("observed_at") or ""))
            if target_ref and evidence_ref and correlation_id and observed_at is not None:
                self._cost_evidence[target_ref] = (evidence_ref, observed_at, correlation_id)
        return restored

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
            cost_ref, cost_observed_at, cost_correlation_id = cost
            if cost_correlation_id != evidence.correlation_id:
                self.record_behavior("capacity_graduation:cost_evidence_uncorrelated")
            elif evidence.observed_at.astimezone(UTC) > cost_observed_at + _COST_EVIDENCE_MAX_AGE:
                self.record_behavior("capacity_graduation:cost_evidence_stale")
            else:
                evidence = evidence.model_copy(
                    update={
                        "cost_evidence_ref": cost_ref,
                        "cost_observed_at": cost_observed_at,
                    }
                )
        else:
            self.record_behavior("capacity_graduation:cost_evidence_missing")
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

    async def _retain_cost_evidence(self, payload: dict[str, Any]) -> None:
        target_ref = _retained_identifier(payload.get("resource_id") or payload.get("target_ref"))
        evidence_ref = _retained_identifier(payload.get("evidence_ref") or payload.get("id"))
        correlation_id = _retained_identifier(payload.get("correlation_id"))
        raw_observed = payload.get("observed_at") or payload.get("detected_at")
        if (
            not target_ref
            or not evidence_ref
            or not correlation_id
            or not isinstance(raw_observed, str)
        ):
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
        retained_at = observed_at.astimezone(UTC)
        async with self._cost_evidence_lock:
            existing = self._cost_evidence.get(target_ref)
            if existing is not None and retained_at < existing[1]:
                self.record_behavior("capacity_graduation:stale_cost_evidence")
                return
            cutoff = retained_at - _COST_EVIDENCE_MAX_AGE
            stale_targets: list[str] = []
            for oldest_target, oldest in self._cost_evidence.items():
                if oldest[1] >= cutoff:
                    break
                stale_targets.append(oldest_target)
            retained_size = len(self._cost_evidence) - len(stale_targets)
            if target_ref in self._cost_evidence and target_ref not in stale_targets:
                retained_size -= 1
            oldest_over_cap: str | None = None
            if retained_size >= _MAX_COST_EVIDENCE:
                for candidate_target, candidate in self._cost_evidence.items():
                    if candidate_target in stale_targets or candidate_target == target_ref:
                        continue
                    if retained_at <= candidate[1]:
                        self.record_behavior("capacity_graduation:cost_evidence_retention_full")
                        return
                    oldest_over_cap = candidate_target
                    break
            if self._state_store is not None:
                await self._state_store.write_state(
                    f"{_COST_PREFIX}{_digest(target_ref)}",
                    {
                        "schema_version": "1.0.0",
                        "revision": 1,
                        "target_ref": target_ref,
                        "evidence_ref": evidence_ref,
                        "observed_at": retained_at.isoformat(),
                        "correlation_id": correlation_id,
                    },
                )
                await self._state_store.delete_states_beyond(
                    _COST_PREFIX,
                    retain_newest=_MAX_COST_EVIDENCE,
                )
            for stale_target in stale_targets:
                self._cost_evidence.pop(stale_target, None)
            if oldest_over_cap is not None:
                self._cost_evidence.pop(oldest_over_cap, None)
            self._cost_evidence.pop(target_ref, None)
            self._cost_evidence[target_ref] = (
                evidence_ref,
                retained_at,
                correlation_id,
            )
        self.record_behavior("capacity_graduation:cost_evidence_retained")

    async def ingest_utilization(
        self,
        *,
        resource_id: str,
        utilization: float,
        correlation_id: str = "",
        observed_at: str = "",
        sample_key: str = "",
    ) -> None:
        observed_at = self._normalize_observed_at(observed_at)
        if not observed_at:
            return
        parsed_observed_at = _parse_observed_at(observed_at)
        if parsed_observed_at is None:
            self.record_behavior("capacity_sample:invalid_observed_at")
            return
        normalized_key = sample_key.strip() or stable_idempotency_key(
            "freyr-capacity-sample",
            resource_id,
            utilization,
            observed_at,
            correlation_id,
        )
        async with self._resource_lock(resource_id):
            if not await self._begin_sample(normalized_key, resource_id, observed_at):
                return
            latest = self._latest_observed_at.get(resource_id)
            if latest is not None and parsed_observed_at < latest:
                self.record_behavior("capacity_sample:stale")
                # A stale sample is terminal; completing its fence makes redelivery a duplicate.
                await self._complete_sample(normalized_key, resource_id, observed_at)
                return
            prev_value = self._smoothed.get(resource_id)
            prev = utilization if prev_value is None else prev_value
            smoothed = self._alpha * utilization + (1 - self._alpha) * prev
            prior_history = self._samples.get(resource_id) or []
            history = [*prior_history, utilization]
            # Trim in place to the rolling cap - only the tail and the length are
            # read, so dropping older samples changes no decision but bounds
            # memory on a long-lived capacity watcher.
            history = history[-_MAX_SAMPLES:]
            await self._persist_resource(resource_id, smoothed, history, parsed_observed_at)
            self._smoothed.set(resource_id, smoothed)
            self._samples.set(resource_id, history)
            self._latest_observed_at[resource_id] = parsed_observed_at
            if self.bus is not None:
                await self._publish_capacity_forecast(
                    resource_id=resource_id,
                    correlation_id=correlation_id,
                    observed_at=observed_at,
                    smoothed=smoothed,
                    history=history,
                )
            else:
                self.record_behavior("capacity_forecast:transport_unavailable")
            await self._complete_sample(normalized_key, resource_id, observed_at)

    async def _publish_capacity_forecast(
        self,
        *,
        resource_id: str,
        correlation_id: str,
        observed_at: str,
        smoothed: float,
        history: list[float],
    ) -> None:
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
                    "idempotency_key": stable_idempotency_key(
                        "capacity-forecast",
                        correlation_id or resource_id,
                        resource_id,
                        observed_at,
                        smoothed,
                        len(history),
                    ),
                    "resource_id": resource_id,
                    "forecast_util": smoothed,
                    "impact": impact,
                    "recent_samples": len(history),
                    # Sizing action doubles as the arbitration recommendation
                    # (scale_up under high utilization can conflict with a
                    # cost-driven scale_down).
                    "recommendation": advice.action,
                    "action_arguments": action_arguments,
                    "observed_at": observed_at,
                },
            )

    async def _begin_sample(
        self,
        sample_key: str,
        resource_id: str,
        observed_at: str,
    ) -> bool:
        if sample_key in self._accepted_sample_keys:
            self.record_behavior("capacity_sample:duplicate")
            return False
        if self._state_store is not None:
            existing = await self._state_store.read_state(_accepted_key(sample_key))
            if existing is not None and existing.get("state") == "completed":
                self._accepted_sample_keys.add(sample_key)
                self.record_behavior("capacity_sample:duplicate")
                return False
            if existing is None:
                await self._state_store.write_state_if_absent(
                    _accepted_key(sample_key),
                    {
                        "schema_version": "1.0.0",
                        "revision": 1,
                        "state": "pending",
                        "sample_key": sample_key,
                        "resource_id": resource_id,
                        "observed_at": observed_at,
                    },
                )
        return True

    async def _complete_sample(
        self,
        sample_key: str,
        resource_id: str,
        observed_at: str,
    ) -> None:
        if self._state_store is not None:
            await self._state_store.write_state(
                _accepted_key(sample_key),
                {
                    "schema_version": "1.0.0",
                    "revision": 2,
                    "state": "completed",
                    "sample_key": sample_key,
                    "resource_id": resource_id,
                    "observed_at": observed_at,
                },
            )
        self._accepted_sample_keys.add(sample_key)
        if self._state_store is not None:
            await self._state_store.delete_states_beyond(
                _ACCEPTED_PREFIX,
                retain_newest=_MAX_TRACKED_RESOURCES * 4,
            )

    async def _persist_resource(
        self,
        resource_id: str,
        smoothed: float,
        history: list[float],
        observed_at: datetime,
    ) -> None:
        if self._state_store is None:
            return
        await self._state_store.write_state(
            f"{_RESOURCE_PREFIX}{_digest(resource_id)}",
            {
                "schema_version": "1.0.0",
                "revision": len(history),
                "resource_id": resource_id,
                "smoothed": smoothed,
                "samples": list(history[-_MAX_SAMPLES:]),
                "latest_observed_at": observed_at.astimezone(UTC).isoformat(),
            },
        )
        await self._state_store.delete_states_beyond(
            _RESOURCE_PREFIX,
            retain_newest=_MAX_TRACKED_RESOURCES,
        )

    def _normalize_observed_at(self, observed_at: str) -> str:
        if not observed_at:
            self._source_time_missing_samples += 1
            self.record_behavior("capacity_sample:source_time_missing")
            return ""
        try:
            parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            self.record_behavior("capacity_sample:invalid_observed_at")
            return ""
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            self.record_behavior("capacity_sample:invalid_observed_at")
            return ""
        return parsed.isoformat()

    @asynccontextmanager
    async def _resource_lock(self, resource_id: str) -> AsyncIterator[None]:
        lock = self._lock_for_resource(resource_id)
        self._resource_lock_refs[resource_id] = self._resource_lock_refs.get(resource_id, 0) + 1
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._resource_lock_refs.get(resource_id, 1) - 1
            if remaining > 0:
                self._resource_lock_refs[resource_id] = remaining
            else:
                self._resource_lock_refs.pop(resource_id, None)
                self._resource_locks.pop(resource_id, None)

    def _lock_for_resource(self, resource_id: str) -> asyncio.Lock:
        lock = self._resource_locks.get(resource_id)
        if lock is None:
            lock = asyncio.Lock()
            self._resource_locks[resource_id] = lock
        return lock

    def sizing_advice(self, resource_id: str) -> SizingRecommendation:
        samples = self._samples.get(resource_id)
        current = samples[-1] if samples else 0.0
        forecast_value = self._smoothed.get(resource_id)
        forecast = current if forecast_value is None else forecast_value
        if forecast >= self._up:
            action = "scale_up"
        elif forecast <= self._down and len(samples or []) >= 3:
            action = "scale_down"
        else:
            action = "hold"
        return SizingRecommendation(
            resource_id=resource_id,
            current_util=current,
            forecast_util=forecast,
            action=action,
        )


def _parse_observed_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _accepted_key(sample_key: str) -> str:
    return f"{_ACCEPTED_PREFIX}{_digest(sample_key)}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _retained_identifier(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if not normalized:
        return ""
    unsafe = (
        len(normalized) > _MAX_RETAINED_IDENTIFIER_CHARS
        or "://" in normalized
        or any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in normalized)
    )
    if unsafe:
        return "sha256:" + _digest(normalized)
    return normalized
