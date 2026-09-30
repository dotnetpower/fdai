"""Bounded canonical event parsing for domain-specialist ingress."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.core.capacity import CapacityGraduationEvidence
from fdai.shared.providers.cost_governance import COST_SAMPLE_EVENT_TYPE

COST_SAMPLE_EVENT = COST_SAMPLE_EVENT_TYPE
CAPACITY_SAMPLE_EVENT = "specialist.capacity_sample"
CAPACITY_GRADUATION_EVENT = "specialist.capacity_graduation_evidence"
CHAOS_SCHEDULE_EVENT = "specialist.chaos_schedule"
SPECIALIST_EVENT_PREFIX = "specialist."
CHAOS_ACTION_TYPES = frozenset({"tool.run-chaos-experiment"})

_MAX_FIELD_CHARS = 512
_MAX_TARGETS = 32


@dataclass(frozen=True, slots=True)
class CostSampleSignal:
    scope: str
    amount_usd: float
    resource_id: str | None
    correlation_id: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class CapacitySampleSignal:
    resource_id: str
    utilization: float
    correlation_id: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class ChaosScheduleSignal:
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    correlation_id: str


def parse_cost_sample(payload: Mapping[str, Any]) -> CostSampleSignal | None:
    attributes = _attributes(payload, COST_SAMPLE_EVENT)
    if attributes is None:
        return None
    scope = _bounded_string(attributes.get("scope"))
    amount = _finite_number(attributes.get("amount_usd"))
    resource_id = _envelope_resource_id(payload, attributes, required=False)
    if scope is None or amount is None or amount < 0:
        return None
    return CostSampleSignal(
        scope=scope,
        amount_usd=amount,
        resource_id=resource_id,
        correlation_id=_correlation_id(payload),
        observed_at=_observed_at(payload),
    )


def parse_capacity_sample(payload: Mapping[str, Any]) -> CapacitySampleSignal | None:
    attributes = _attributes(payload, CAPACITY_SAMPLE_EVENT)
    if attributes is None:
        return None
    resource_id = _envelope_resource_id(payload, attributes)
    utilization = _finite_number(attributes.get("utilization"))
    if resource_id is None or utilization is None or not 0 <= utilization <= 1:
        return None
    return CapacitySampleSignal(
        resource_id=resource_id,
        utilization=utilization,
        correlation_id=_correlation_id(payload),
        observed_at=_source_observed_at(payload),
    )


def parse_capacity_graduation_evidence(
    payload: Mapping[str, Any],
) -> CapacityGraduationEvidence | None:
    """Parse one exact measurement receipt without filling missing cost evidence."""

    attributes = _attributes(payload, CAPACITY_GRADUATION_EVENT)
    if attributes is None:
        return None
    values = dict(attributes)
    values["correlation_id"] = _correlation_id(payload)
    values["observed_at"] = _observed_at(payload)
    values.setdefault("target_ref", attributes.get("resource_id"))
    try:
        return CapacityGraduationEvidence.model_validate(values)
    except ValueError:
        return None


def parse_chaos_schedule(payload: Mapping[str, Any]) -> ChaosScheduleSignal | None:
    attributes = _attributes(payload, CHAOS_SCHEDULE_EVENT)
    if attributes is None:
        return None
    experiment_id = _bounded_string(attributes.get("experiment_id"))
    action_type = _bounded_string(attributes.get("action_type"))
    raw_targets = attributes.get("targets")
    if (
        experiment_id is None
        or action_type is None
        or action_type not in CHAOS_ACTION_TYPES
        or not isinstance(raw_targets, Sequence)
        or isinstance(raw_targets, str | bytes)
        or not 1 <= len(raw_targets) <= _MAX_TARGETS
    ):
        return None
    targets = tuple(_bounded_string(item) for item in raw_targets)
    if any(target is None for target in targets):
        return None
    return ChaosScheduleSignal(
        experiment_id=experiment_id,
        action_type=action_type,
        targets=tuple(target for target in targets if target is not None),
        correlation_id=_correlation_id(payload),
    )


def _attributes(payload: Mapping[str, Any], event_type: str) -> Mapping[str, Any] | None:
    if payload.get("event_type") != event_type:
        return None
    attributes = payload.get("attributes")
    return attributes if isinstance(attributes, Mapping) else None


def _bounded_string(value: object, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAX_FIELD_CHARS
        or any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in normalized)
    ):
        return None
    return normalized


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _correlation_id(payload: Mapping[str, Any]) -> str:
    value = _bounded_string(payload.get("correlation_id"), required=False)
    return value or ""


def _observed_at(payload: Mapping[str, Any]) -> str:
    value = _bounded_string(payload.get("occurred_at"), required=False) or _bounded_string(
        payload.get("ingested_at"), required=False
    )
    return value or ""


def _source_observed_at(payload: Mapping[str, Any]) -> str:
    value = _bounded_string(payload.get("occurred_at"), required=False)
    return value or ""


def _envelope_resource_id(
    payload: Mapping[str, Any],
    attributes: Mapping[str, Any],
    *,
    required: bool = True,
) -> str | None:
    envelope_resource = _bounded_string(payload.get("resource_id"), required=required)
    attribute_resource = _bounded_string(attributes.get("resource_id"), required=False)
    if envelope_resource is None:
        return attribute_resource if not required else None
    if attribute_resource is not None and attribute_resource != envelope_resource:
        return None
    return envelope_resource


def has_resource_id_conflict(payload: Mapping[str, Any]) -> bool:
    """Return whether the attribute copy conflicts with the authoritative envelope."""

    attributes = payload.get("attributes")
    if not isinstance(attributes, Mapping):
        return False
    envelope_resource = _bounded_string(payload.get("resource_id"), required=False)
    attribute_resource = _bounded_string(attributes.get("resource_id"), required=False)
    return (
        envelope_resource is not None
        and attribute_resource is not None
        and attribute_resource != envelope_resource
    )


__all__ = [
    "CAPACITY_SAMPLE_EVENT",
    "CAPACITY_GRADUATION_EVENT",
    "CHAOS_ACTION_TYPES",
    "CHAOS_SCHEDULE_EVENT",
    "COST_SAMPLE_EVENT",
    "SPECIALIST_EVENT_PREFIX",
    "CapacitySampleSignal",
    "ChaosScheduleSignal",
    "CostSampleSignal",
    "has_resource_id_conflict",
    "parse_capacity_sample",
    "parse_capacity_graduation_evidence",
    "parse_chaos_schedule",
    "parse_cost_sample",
]
