"""Freyr - Capacity (Wave 5 behavior).

Freyr samples utilization, projects forward via a light exponential
smoothing forecast, and exposes a sizing advisory hook.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.freyr_capacity_runtime import (
    _MAX_SAMPLES as _MAX_SAMPLES,
)
from fdai.agents._framework.freyr_capacity_runtime import (
    FreyrCapacityRuntimeMixin,
    SizingRecommendation,
)
from fdai.agents._framework.freyr_constants import (
    _ACCEPTED_PREFIX as _ACCEPTED_PREFIX,
)
from fdai.agents._framework.freyr_constants import (
    _COST_EVIDENCE_MAX_AGE as _COST_EVIDENCE_MAX_AGE,
)
from fdai.agents._framework.freyr_constants import (
    _COST_PREFIX as _COST_PREFIX,
)
from fdai.agents._framework.freyr_constants import (
    _MAX_COST_EVIDENCE as _MAX_COST_EVIDENCE,
)
from fdai.agents._framework.freyr_constants import (
    _MAX_RETAINED_IDENTIFIER_CHARS as _MAX_RETAINED_IDENTIFIER_CHARS,
)
from fdai.agents._framework.freyr_constants import (
    _MAX_TRACKED_RESOURCES as _MAX_TRACKED_RESOURCES,
)
from fdai.agents._framework.freyr_constants import (
    _RESOURCE_PREFIX as _RESOURCE_PREFIX,
)
from fdai.agents._framework.freyr_sampling import (
    MAX_RECURRING_SAMPLES,
    CapacityUtilizationSampler,
)
from fdai.agents._framework.freyr_status_runtime import FreyrStatusRuntimeMixin
from fdai.agents._framework.pantheon import _FREYR
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import (
    CAPACITY_GRADUATION_EVENT,
    CAPACITY_SAMPLE_EVENT,
    has_resource_id_conflict,
    parse_capacity_sample,
)
from fdai.core.capacity import CapacityGraduationController
from fdai.shared.providers.state_store import StateStore


#: Hard cap on retained per-resource utilization samples. The EWMA forecast
#: lives in ``_smoothed``; ``_samples`` is only read for its last value, its
#: length (the >= 3 scale_down guard), and the introspection count - so
#: trimming older samples is behavior-preserving and bounds memory on a
#: long-lived capacity watcher.
class Freyr(
    FreyrCapacityRuntimeMixin,
    FreyrStatusRuntimeMixin,
    Agent,
):
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
        state_store: StateStore | None = None,
        utilization_sampler: CapacityUtilizationSampler | None = None,
        recurring_sample_limit: int = MAX_RECURRING_SAMPLES,
        recurring_sample_timeout: timedelta = timedelta(seconds=5),
    ) -> None:
        super().__init__(spec=_FREYR)
        if recurring_sample_timeout <= timedelta(0):
            raise ValueError("recurring_sample_timeout MUST be positive")
        self.bus = bus
        self._alpha = smoothing_alpha
        self._up = scale_up_threshold
        self._down = scale_down_threshold
        self._smoothed: BoundedLruDict[str, float] = BoundedLruDict(_MAX_TRACKED_RESOURCES)
        self._samples: BoundedLruDict[str, list[float]] = BoundedLruDict(_MAX_TRACKED_RESOURCES)
        self._graduation_controller = graduation_controller
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._cost_evidence: OrderedDict[str, tuple[str, datetime, str]] = OrderedDict()
        self._state_store = state_store
        self._accepted_sample_keys: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED_RESOURCES * 4)
        self._latest_observed_at: dict[str, datetime] = {}
        self._source_time_missing_samples = 0
        self._forecast_errors: list[float] = []
        self._over_provisioned = 0
        self._under_provisioned = 0
        self._provisioning_observations = 0
        self._resource_locks: dict[str, asyncio.Lock] = {}
        self._resource_lock_refs: dict[str, int] = {}
        self._cost_evidence_lock = asyncio.Lock()
        self._utilization_sampler = utilization_sampler
        self._recurring_sample_limit = recurring_sample_limit
        self._recurring_sample_timeout = recurring_sample_timeout

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_utilization_sampler(self, sampler: CapacityUtilizationSampler | None) -> None:
        self._utilization_sampler = sampler

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.cost-anomaly":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="capacity_graduation:invalid_cost_owner",
            ):
                return
            await self._retain_cost_evidence(payload)
            return
        if topic != "object.event":
            self.record_behavior("typed_message:ignored")
            return
        if require_topic_owner(
            self,
            topic,
            payload,
            behavior="capacity_sample:invalid_producer",
        ):
            return
        if payload.get("event_type") == CAPACITY_GRADUATION_EVENT:
            await self._evaluate_graduation(payload)
            return
        if payload.get("event_type") != CAPACITY_SAMPLE_EVENT:
            self.record_behavior("capacity_sample:ignored_event")
            return
        if has_resource_id_conflict(payload):
            self.record_behavior("capacity_sample:resource_conflict")
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
            sample_key=str(payload.get("idempotency_key") or payload.get("event_id") or ""),
        )


__all__ = ["Freyr", "SizingRecommendation"]
