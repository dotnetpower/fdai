"""Deterministic recurring chaos scheduling contracts for Loki."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.agents._framework.specialist_ingress import CHAOS_ACTION_TYPES
from fdai.agents._framework.topics import stable_idempotency_key

MAX_SCHEDULE_TARGETS = 32
MAX_SCHEDULE_FIELD_CHARS = 512


@dataclass(frozen=True, slots=True)
class ChaosScheduleConfig:
    """One validated recurring Loki schedule definition."""

    schedule_id: str
    cadence: timedelta
    targets: tuple[str, ...]
    action_type: str = "tool.run-chaos-experiment"
    causal_hypothesis_ref: str = ""
    refutation_query_ref: str = ""
    impact_envelope_id: str = ""
    recovery_plan_id: str = ""
    dry_run_receipt: str = ""
    start_at: datetime | None = None
    correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class DueChaosWindow:
    """A due recurring chaos proposal window."""

    schedule_id: str
    window_start: datetime
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    correlation_id: str
    causal_hypothesis_ref: str
    refutation_query_ref: str
    impact_envelope_id: str
    recovery_plan_id: str
    dry_run_receipt: str


def due_window(config: ChaosScheduleConfig, *, now: datetime) -> DueChaosWindow | str:
    """Return a due complete window, or a stable hold reason."""

    reason = validate_config(config)
    if reason:
        return reason
    start_at = config.start_at or now
    if now < start_at:
        return "not_due"
    elapsed = now - start_at
    window_index = int(elapsed.total_seconds() // config.cadence.total_seconds())
    window_start = start_at + (config.cadence * window_index)
    if not _complete_evidence(config):
        return "incomplete_evidence"
    experiment_id = stable_idempotency_key(
        "loki-recurring-chaos-window",
        config.schedule_id,
        window_start.isoformat(),
        config.action_type,
        config.targets,
    )
    return DueChaosWindow(
        schedule_id=config.schedule_id,
        window_start=window_start,
        experiment_id=experiment_id,
        action_type=config.action_type,
        targets=config.targets,
        correlation_id=config.correlation_id
        or stable_idempotency_key("loki-recurring-chaos-correlation", config.schedule_id),
        causal_hypothesis_ref=config.causal_hypothesis_ref,
        refutation_query_ref=config.refutation_query_ref,
        impact_envelope_id=config.impact_envelope_id,
        recovery_plan_id=config.recovery_plan_id,
        dry_run_receipt=config.dry_run_receipt,
    )


def validate_config(config: ChaosScheduleConfig) -> str:
    """Return an empty string when ``config`` is valid, otherwise a stable reason."""

    if _bounded_string(config.schedule_id) is None:
        return "invalid_schedule_id"
    if config.cadence <= timedelta(0):
        return "invalid_cadence"
    if config.action_type not in CHAOS_ACTION_TYPES:
        return "invalid_action_type"
    if not 1 <= len(config.targets) <= MAX_SCHEDULE_TARGETS:
        return "invalid_targets"
    targets = tuple(_bounded_string(target) for target in config.targets)
    if any(target is None for target in targets) or len(set(config.targets)) != len(config.targets):
        return "invalid_targets"
    return ""


def window_key(window: DueChaosWindow) -> str:
    """Return the durable idempotency key for one recurring chaos window."""

    return stable_idempotency_key(
        "loki-recurring-chaos-durable-window",
        window.schedule_id,
        window.window_start.isoformat(),
    )


def _complete_evidence(config: ChaosScheduleConfig) -> bool:
    return all(
        _bounded_string(value) is not None
        for value in (
            config.causal_hypothesis_ref,
            config.refutation_query_ref,
            config.impact_envelope_id,
            config.recovery_plan_id,
            config.dry_run_receipt,
        )
    )


def _bounded_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_SCHEDULE_FIELD_CHARS
        or any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in normalized)
    ):
        return None
    return normalized


__all__ = [
    "ChaosScheduleConfig",
    "DueChaosWindow",
    "due_window",
    "validate_config",
    "window_key",
]
