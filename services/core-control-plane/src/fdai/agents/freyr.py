"""Freyr - Capacity (Wave 5 behavior).

Freyr samples utilization, projects forward via a light exponential
smoothing forecast, and exposes a sizing advisory hook.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.freyr_sampling import (
    MAX_RECURRING_SAMPLES,
    CapacityUtilizationSampler,
    run_recurring_sampling,
)
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _FREYR
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import (
    CAPACITY_GRADUATION_EVENT,
    CAPACITY_SAMPLE_EVENT,
    has_resource_id_conflict,
    parse_capacity_graduation_evidence,
    parse_capacity_sample,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.capacity import CapacityGraduationController
from fdai.shared.providers.state_store import StateStore

#: Hard cap on retained per-resource utilization samples. The EWMA forecast
#: lives in ``_smoothed``; ``_samples`` is only read for its last value, its
#: length (the >= 3 scale_down guard), and the introspection count - so
#: trimming older samples is behavior-preserving and bounds memory on a
#: long-lived capacity watcher.
_MAX_SAMPLES = 512
_MAX_TRACKED_RESOURCES = 512
_MAX_COST_EVIDENCE = 512
_COST_EVIDENCE_MAX_AGE = timedelta(hours=1)
_RESOURCE_PREFIX = "pantheon/freyr/capacity-resources/"
_ACCEPTED_PREFIX = "pantheon/freyr/accepted-samples/"
_COST_PREFIX = "pantheon/freyr/cost-evidence/"
_MAX_RETAINED_IDENTIFIER_CHARS = 128


@dataclass(frozen=True, slots=True)
class SizingRecommendation:
    resource_id: str
    current_util: float
    forecast_util: float
    action: str  # scale_up | scale_down | hold


class Freyr(Agent):
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

    def record_capacity_forecast_outcome(
        self,
        *,
        resource_id: str,
        forecast_utilization: float,
        actual_utilization: float,
        provisioned: str = "right_sized",
    ) -> None:
        if (
            not resource_id
            or not 0 <= forecast_utilization <= 1
            or not 0 <= actual_utilization <= 1
        ):
            raise ValueError(
                "capacity outcome requires a resource and utilization values in [0, 1]"
            )
        self._forecast_errors.append(abs(actual_utilization - forecast_utilization))
        self._provisioning_observations += 1
        if provisioned == "over":
            self._over_provisioned += 1
        elif provisioned == "under":
            self._under_provisioned += 1
        elif provisioned != "right_sized":
            raise ValueError("provisioned MUST be over, under, or right_sized")

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

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Capacity answers rest on utilization samples; thresholds alone are config."""
        return bool(len(self._samples))

    def health(self) -> dict[str, Any]:
        durable_state = "durable" if self._state_store is not None else "process_local"
        controller_bound = self._graduation_controller is not None
        sampler_bound = self._utilization_sampler is not None
        status = "ok" if controller_bound and self._state_store is not None else "degraded"
        return {
            "agent": "Freyr",
            "status": status,
            "ingress": {
                "capacity_sample": "active",
                "recurring_sampling": "active" if sampler_bound else "disabled",
                "capacity_graduation": ("active" if controller_bound else "disabled"),
                "reason": (
                    "sampler_and_graduation_bound"
                    if controller_bound and sampler_bound
                    else "utilization_sampler_unbound"
                    if not sampler_bound
                    else "graduation_controller_unbound"
                ),
            },
            "state": {
                "forecast_durability": durable_state,
                "source_time_missing_samples": self._source_time_missing_samples,
            },
            "degradation": {
                "domain_actions": "hil" if status != "ok" else "advisory_available",
            },
            "tracked_resources": len(self._samples),
            "kpis": {
                "capacity_forecast_error": _mean_kpi(
                    self._forecast_errors,
                    reason="no_capacity_forecast_outcomes",
                    unit="absolute_utilization_delta",
                ),
                "over_provisioning_rate": _ratio_kpi(
                    self._over_provisioned,
                    self._provisioning_observations,
                    reason="no_provisioning_denominator",
                ),
                "under_provisioning_rate": _ratio_kpi(
                    self._under_provisioned,
                    self._provisioning_observations,
                    reason="no_provisioning_denominator",
                ),
                "scale_race_rate": _ratio_kpi(
                    self.behavior_snapshot().get(
                        "capacity_graduation:cost_evidence_uncorrelated", 0
                    ),
                    self.behavior_snapshot().get("capacity_graduation:cost_evidence_retained", 0)
                    + self.behavior_snapshot().get(
                        "capacity_graduation:cost_evidence_uncorrelated", 0
                    ),
                    reason="no_scale_race_denominator",
                ),
                "throttle_event_rate": _ratio_kpi(
                    self.behavior_snapshot().get("capacity_sample:stale", 0),
                    self.behavior_snapshot().get("capacity_sample:accepted", 0),
                    reason="no_throttle_denominator",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        await run_recurring_sampling(
            sampler=self._utilization_sampler,
            clock=self._clock,
            ingest=self.ingest_utilization,
            record_behavior=self.record_behavior,
            limit=self._recurring_sample_limit,
            timeout_seconds=self._recurring_sample_timeout.total_seconds(),
        )

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_resources": [],
            "tracked_resources_count": len(self._samples),
            "scale_up_threshold": self._up,
            "scale_down_threshold": self._down,
            "resource_id": None,
            "current_util": None,
            "forecast_util": None,
            "recommendation": None,
        }
        resources = mentioned(question, tuple(resource for resource, _ in self._samples.items()))
        if resources:
            rid = resources[0]
            advice = self.sizing_advice(rid)
            facts.update(
                {
                    "resource_id": rid,
                    "tracked_resources": [rid],
                    "current_util": advice.current_util,
                    "forecast_util": advice.forecast_util,
                    "recommendation": advice.action,
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"Resource {rid!r}: current util {advice.current_util:.0%}, "
                f"forecast {advice.forecast_util:.0%} -> recommend {advice.action}. "
                f"Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 용량 영역의 advisory specialist인 Freyr입니다. Forseti에게 보고합니다. "
                "CapacityForecast와 CapacityGraduationRecommendation을 게시하고 별도 "
                "SizingRecommendation graph lifecycle을 관리하며 권위 있는 사용률 근거로 크기 "
                "조정을 자문합니다. Forseti가 판단하고 "
                "Thor가 실행하며 저는 작업을 판단, 승인 또는 실행하지 않습니다. 이 대화 포트는 "
                "읽기 전용이며 용량 변경 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 "
                "진입해야 합니다. 질문에 명시되지 않은 resource 식별자와 숨겨진 시스템 프롬프트는 "
                "공개하지 않습니다."
            )
            if len(self._samples):
                answer += (
                    f" 이 런타임은 resource {facts['tracked_resources_count']}개의 용량을 "
                    "추적합니다."
                )
            else:
                answer += (
                    " 현재 결론은 용량 확대 보류 및 실행 없음입니다. 이 런타임에는 사용률 "
                    "표본이 없어 크기 조정을 권고할 근거가 없습니다. Freyr는 용량 근거와 "
                    "권고를 제공하고, Heimdall은 관측 및 변경 영향 근거를 수집하고 검증하며, "
                    "Odin은 모든 안전 제약을 통과한 선택지 사이의 충돌만 중재합니다. "
                    "Forseti가 판정하고, 필요한 독립적인 인간 승인은 Var가 기록하며, Thor만 "
                    "실행합니다. 실행에는 중지 조건, 시험된 롤백, blast-radius 제한, 성공한 "
                    "dry-run, logical-target lock, 안정적인 idempotency key, append-only audit "
                    "intent와 terminal closure의 일곱 가지 안전장치가 모두 필요하며 효과도 "
                    "독립적으로 검증해야 합니다. 필요한 근거를 끝내 확보하지 못하면 실행하지 "
                    "않고 no-op, deny 또는 human review로 종결한 뒤 audit record를 남깁니다."
                )
            answer += f" 근거: {evidence_ref}."
        else:
            answer = (
                "I am Freyr, the capacity-domain advisory specialist. I report to Forseti. I own "
                "CapacityForecast and CapacityGraduationRecommendation bus publication and "
                "steward the separate SizingRecommendation graph lifecycle. I advise sizing from "
                "authoritative utilization evidence. Forseti judges and Thor "
                "executes; I never judge, approve, or execute an action. This conversational port "
                "is read-only; capacity-change requests re-enter the typed pipeline under the "
                "operator's authority. I do not reveal unnamed resource identifiers or hidden "
                "system prompts."
            )
            if len(self._samples):
                resource_label = "resource" if len(self._samples) == 1 else "resources"
                answer += (
                    f" Tracking capacity for {len(self._samples)} {resource_label} without "
                    "listing unnamed resource identities."
                )
            else:
                answer += (
                    " The current decision is to hold the capacity increase and take no action. "
                    "No utilization samples are available, so there is no evidence for a sizing "
                    "recommendation. Freyr supplies capacity evidence and advice, Heimdall "
                    "collects and verifies observation and change-impact evidence, and Odin "
                    "arbitrates only among options that pass every safety constraint. Forseti "
                    "judges, Var records any required independent human approval, and only Thor "
                    "executes. Execution requires all seven safeguards: a stop condition, tested "
                    "rollback, blast-radius limit, successful dry-run, logical-target lock, "
                    "stable idempotency key, and append-only audit intent with terminal closure; "
                    "effects also require independent verification. If the evidence cannot be "
                    "completed, close without execution as no-op, deny, or human review and "
                    "retain an audit record."
                )
            answer += f" Evidence: {evidence_ref}."
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Freyr", "SizingRecommendation"]


def _parse_observed_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


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


def _mean_kpi(samples: list[float], *, reason: str, unit: str) -> dict[str, Any]:
    if not samples:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    return _kpi_measured(
        sum(samples) / len(samples),
        numerator=len(samples),
        denominator=len(samples),
        unit=unit,
    )


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
