"""Calculate bounded adaptive collection schedules without performing I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.delivery.inventory_source_policy import SourceCollectionPolicy


class ProviderPressure(StrEnum):
    """Describe the provider condition observed by the previous attempt."""

    HEALTHY = "healthy"
    QUOTA_PRESSURE = "quota_pressure"
    THROTTLED = "throttled"
    TIMEOUT = "timeout"
    NO_PROGRESS = "no_progress"
    CIRCUIT_OPEN = "circuit_open"
    RECOVERING = "recovering"


class CollectionScheduleAction(StrEnum):
    """Name the next bounded scheduler action."""

    WAIT = "wait"
    COLLECT = "collect"
    PROBE = "probe"


@dataclass(frozen=True, slots=True)
class CollectionScheduleState:
    """Carry authoritative scheduling inputs without provider payloads."""

    evidence_age_seconds: float | None
    last_attempt_age_seconds: float | None
    cursor_lag_seconds: float = 0.0
    overlay_open: bool = False
    change_demand: bool = False
    critical: bool = False
    operator_requested: bool = False
    stable_cycles: int = 0
    failure_streak: int = 0
    provider_pressure: ProviderPressure = ProviderPressure.HEALTHY
    retry_after_seconds: float | None = None
    budget_remaining_ratio: float = 1.0
    budget_reset_seconds: float | None = None
    jitter_fraction: float = 0.5

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_age_seconds",
            "last_attempt_age_seconds",
            "cursor_lag_seconds",
            "retry_after_seconds",
            "budget_reset_seconds",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"collection schedule {field_name} MUST NOT be negative")
        if self.stable_cycles < 0 or self.failure_streak < 0:
            raise ValueError("collection schedule cycle and failure counts MUST NOT be negative")
        if not 0.0 <= self.budget_remaining_ratio <= 1.0:
            raise ValueError("collection schedule budget_remaining_ratio MUST be in [0, 1]")
        if not 0.0 <= self.jitter_fraction <= 1.0:
            raise ValueError("collection schedule jitter_fraction MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CollectionScheduleDecision:
    """Describe one due decision and its bounded execution posture."""

    action: CollectionScheduleAction
    due_in_seconds: float
    interval_seconds: float
    priority: int
    concurrency_limit: int
    freshness_available: bool
    reason_codes: tuple[str, ...]

    @property
    def due(self) -> bool:
        """Return whether the controller selected work for this tick."""

        return self.action is not CollectionScheduleAction.WAIT


def calculate_collection_schedule(
    policy: SourceCollectionPolicy,
    state: CollectionScheduleState,
) -> CollectionScheduleDecision:
    """Reduce freshness, demand, and provider pressure to one bounded action.

    Pressure controls always outrank demand. Operator priority can advance healthy work but cannot
    bypass Retry-After, exhausted quota, an open circuit, or a recovery probe.
    """

    priority = _priority(policy, state)
    pressure = state.provider_pressure
    if pressure is ProviderPressure.CIRCUIT_OPEN or _opens_circuit(policy, state):
        return _circuit_decision(policy, state, priority)
    if pressure is ProviderPressure.THROTTLED:
        delay = max(
            state.retry_after_seconds or 0.0,
            _failure_backoff(policy, max(1, state.failure_streak)),
        )
        return _delayed_probe(
            state=state,
            delay=delay,
            priority=priority,
            reason="provider_retry_after" if state.retry_after_seconds is not None else "throttled",
            freshness_available=False,
        )
    if pressure in {ProviderPressure.TIMEOUT, ProviderPressure.NO_PROGRESS}:
        return _delayed_probe(
            state=state,
            delay=_failure_backoff(policy, max(1, state.failure_streak)),
            priority=priority,
            reason=pressure.value,
            freshness_available=False,
        )
    if pressure is ProviderPressure.RECOVERING:
        return _delayed_probe(
            state=state,
            delay=float(policy.min_poll_interval_seconds),
            priority=priority,
            reason="recovery_probe",
            freshness_available=False,
        )
    if pressure is ProviderPressure.QUOTA_PRESSURE:
        return _quota_decision(policy, state, priority)
    return _healthy_decision(policy, state, priority)


def _healthy_decision(
    policy: SourceCollectionPolicy,
    state: CollectionScheduleState,
    priority: int,
) -> CollectionScheduleDecision:
    reasons: list[str] = []
    if state.operator_requested:
        reasons.append("operator_requested")
        interval = float(policy.min_poll_interval_seconds)
    elif state.change_demand:
        reasons.append("change_demand")
        interval = float(policy.min_poll_interval_seconds)
    elif state.overlay_open or state.cursor_lag_seconds > 0:
        reasons.append("cursor_lag" if state.cursor_lag_seconds > 0 else "overlay_open")
        interval = float(policy.min_poll_interval_seconds)
    elif state.evidence_age_seconds is None:
        reasons.append("freshness_unknown")
        interval = float(policy.min_poll_interval_seconds)
    else:
        reasons.append("healthy")
        growth = 2 ** min(state.stable_cycles, 16)
        interval = float(
            min(
                policy.max_poll_interval_seconds,
                policy.target_freshness_seconds * growth,
                policy.max_staleness_seconds,
            )
        )
    interval = _apply_jitter(policy, state, interval)
    last_attempt_age = state.last_attempt_age_seconds
    if state.operator_requested:
        due_in = 0.0
    elif state.evidence_age_seconds is None:
        due_in = 0.0 if last_attempt_age is None else _remaining(last_attempt_age, interval)
    elif state.evidence_age_seconds >= policy.max_staleness_seconds:
        reasons.append("maximum_staleness")
        due_in = _remaining(last_attempt_age, float(policy.min_poll_interval_seconds))
    elif state.change_demand or state.overlay_open or state.cursor_lag_seconds > 0:
        due_in = _remaining(last_attempt_age, interval)
    else:
        due_in = max(0.0, interval - state.evidence_age_seconds)
    action = CollectionScheduleAction.COLLECT if due_in == 0 else CollectionScheduleAction.WAIT
    return CollectionScheduleDecision(
        action=action,
        due_in_seconds=due_in,
        interval_seconds=interval,
        priority=priority,
        concurrency_limit=policy.endpoint_concurrency_limit,
        freshness_available=state.evidence_age_seconds is not None,
        reason_codes=tuple(reasons),
    )


def _quota_decision(
    policy: SourceCollectionPolicy,
    state: CollectionScheduleState,
    priority: int,
) -> CollectionScheduleDecision:
    if state.budget_remaining_ratio == 0:
        delay = state.budget_reset_seconds or float(policy.budget_window_seconds)
        return _wait(
            delay=_remaining(state.last_attempt_age_seconds, delay),
            interval=delay,
            priority=priority,
            concurrency=1,
            freshness_available=False,
            reasons=("quota_exhausted",),
        )
    multiplier = 1.0 + (1.0 - state.budget_remaining_ratio) * 3.0
    interval = min(
        float(policy.max_poll_interval_seconds),
        float(policy.target_freshness_seconds) * multiplier,
    )
    due_in = _remaining(state.last_attempt_age_seconds, interval)
    concurrency = max(1, int(policy.endpoint_concurrency_limit * state.budget_remaining_ratio))
    return CollectionScheduleDecision(
        action=(CollectionScheduleAction.COLLECT if due_in == 0 else CollectionScheduleAction.WAIT),
        due_in_seconds=due_in,
        interval_seconds=interval,
        priority=priority,
        concurrency_limit=concurrency,
        freshness_available=state.evidence_age_seconds is not None,
        reason_codes=("quota_pressure",),
    )


def _circuit_decision(
    policy: SourceCollectionPolicy,
    state: CollectionScheduleState,
    priority: int,
) -> CollectionScheduleDecision:
    return _delayed_probe(
        state=state,
        delay=float(policy.circuit_probe_interval_seconds),
        priority=priority,
        reason="circuit_open",
        freshness_available=False,
    )


def _delayed_probe(
    *,
    state: CollectionScheduleState,
    delay: float,
    priority: int,
    reason: str,
    freshness_available: bool,
) -> CollectionScheduleDecision:
    due_in = _remaining(state.last_attempt_age_seconds, delay)
    return CollectionScheduleDecision(
        action=CollectionScheduleAction.PROBE if due_in == 0 else CollectionScheduleAction.WAIT,
        due_in_seconds=due_in,
        interval_seconds=delay,
        priority=priority,
        concurrency_limit=1,
        freshness_available=freshness_available,
        reason_codes=(reason,),
    )


def _wait(
    *,
    delay: float,
    interval: float,
    priority: int,
    concurrency: int,
    freshness_available: bool,
    reasons: tuple[str, ...],
) -> CollectionScheduleDecision:
    return CollectionScheduleDecision(
        action=(CollectionScheduleAction.PROBE if delay == 0 else CollectionScheduleAction.WAIT),
        due_in_seconds=delay,
        interval_seconds=interval,
        priority=priority,
        concurrency_limit=concurrency,
        freshness_available=freshness_available,
        reason_codes=reasons,
    )


def _priority(policy: SourceCollectionPolicy, state: CollectionScheduleState) -> int:
    priority = policy.priority.base
    if state.change_demand or state.overlay_open or state.cursor_lag_seconds > 0:
        priority += policy.priority.changed_boost
    if state.evidence_age_seconds is None or (
        state.evidence_age_seconds >= policy.target_freshness_seconds
    ):
        priority += policy.priority.stale_boost
    if state.critical:
        priority += policy.priority.critical_boost
    if state.operator_requested:
        priority += policy.priority.operator_requested_boost
    return priority


def _opens_circuit(policy: SourceCollectionPolicy, state: CollectionScheduleState) -> bool:
    return (
        state.provider_pressure
        in {ProviderPressure.THROTTLED, ProviderPressure.TIMEOUT, ProviderPressure.NO_PROGRESS}
        and state.failure_streak >= policy.circuit_failure_threshold
    )


def _failure_backoff(policy: SourceCollectionPolicy, failure_streak: int) -> float:
    exponent = min(max(0, failure_streak - 1), 32)
    return float(
        min(
            policy.backoff_max_seconds,
            policy.backoff_base_seconds * (2**exponent),
        )
    )


def _apply_jitter(
    policy: SourceCollectionPolicy,
    state: CollectionScheduleState,
    interval: float,
) -> float:
    offset = (state.jitter_fraction * 2.0) - 1.0
    jittered = interval * (1.0 + float(policy.jitter_ratio) * offset)
    return min(
        float(policy.max_staleness_seconds),
        max(float(policy.min_poll_interval_seconds), jittered),
    )


def _remaining(age_seconds: float | None, delay_seconds: float) -> float:
    return max(0.0, delay_seconds - (age_seconds or 0.0))


__all__ = [
    "CollectionScheduleAction",
    "CollectionScheduleDecision",
    "CollectionScheduleState",
    "ProviderPressure",
    "calculate_collection_schedule",
]
