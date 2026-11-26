"""Bounded canonical event parsing for domain-specialist ingress."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.core.capacity import CapacityGraduationEvidence
from fdai.shared.providers.cost_governance import (
    COST_OPTIMIZATION_EVENT_TYPE,
    COST_SAMPLE_EVENT_TYPE,
)

COST_SAMPLE_EVENT = COST_SAMPLE_EVENT_TYPE
COST_OPTIMIZATION_EVENT = COST_OPTIMIZATION_EVENT_TYPE
CAPACITY_SAMPLE_EVENT = "specialist.capacity_sample"
CAPACITY_GRADUATION_EVENT = "specialist.capacity_graduation_evidence"
CHAOS_SCHEDULE_EVENT = "specialist.chaos_schedule"
RESILIENCE_SCORE_EVENT = "specialist.resilience_score"
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
class CostOptimizationSignal:
    candidate: dict[str, Any]
    activation_revision: int


@dataclass(frozen=True, slots=True)
class ChaosScheduleSignal:
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ResilienceScoreSignal:
    resource_id: str
    score: float
    experiment_id: str
    correlation_id: str
    observed_at: str


def parse_cost_sample(payload: Mapping[str, Any]) -> CostSampleSignal | None:
    attributes = _attributes(payload, COST_SAMPLE_EVENT)
    if attributes is None:
        return None
    scope = _bounded_string(attributes.get("scope"))
    amount = _finite_number(attributes.get("amount_usd"))
    resource_id = _envelope_resource_id(payload, attributes, required=False)
    if scope is None or amount is None or amount < 0:
        return None
    observed_at = (
        _observed_at(payload)
        or _bounded_string(attributes.get("observed_at"), required=False)
        or _bounded_string(payload.get("detected_at"), required=False)
        or ""
    )
    return CostSampleSignal(
        scope=scope,
        amount_usd=amount,
        resource_id=resource_id,
        correlation_id=_correlation_id(payload),
        observed_at=observed_at,
    )


def parse_cost_optimization(payload: Mapping[str, Any]) -> CostOptimizationSignal | None:
    attributes = _attributes(payload, COST_OPTIMIZATION_EVENT)
    if attributes is None:
        return None
    activation_revision = attributes.get("activation_revision")
    candidate = attributes.get("candidate")
    if (
        isinstance(activation_revision, bool)
        or not isinstance(activation_revision, int)
        or activation_revision < 0
        or not isinstance(candidate, Mapping)
    ):
        return None
    normalized = {str(key): value for key, value in candidate.items() if isinstance(key, str)}
    if (
        len(normalized) != len(candidate)
        or "producer_principal" in normalized
        or normalized.get("kind") != "cross_vertical_candidate"
        or normalized.get("resource_id") != payload.get("resource_id")
        or normalized.get("correlation_id") != payload.get("correlation_id")
        or normalized.get("idempotency_key") != payload.get("idempotency_key")
        or normalized.get("observed_at") != payload.get("occurred_at")
    ):
        return None
    forbidden = {
        "approval",
        "approval_required",
        "execution_authority",
        "executor_principal",
        "promotion_authority",
    }
    if forbidden & set(normalized):
        return None
    return CostOptimizationSignal(
        candidate=normalized,
        activation_revision=activation_revision,
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
    clean_targets = tuple(target for target in targets if target is not None)
    if len(set(clean_targets)) != len(clean_targets):
        return None
    return ChaosScheduleSignal(
        experiment_id=experiment_id,
        action_type=action_type,
        targets=clean_targets,
        correlation_id=_correlation_id(payload),
    )


def parse_resilience_score(payload: Mapping[str, Any]) -> ResilienceScoreSignal | None:
    attributes = _attributes(payload, RESILIENCE_SCORE_EVENT)
    if attributes is None:
        return None
    resource_id = _envelope_resource_id(payload, attributes)
    score = _finite_number(attributes.get("score"))
    experiment_id = _bounded_string(attributes.get("experiment_id"), required=False) or ""
    if resource_id is None or score is None or not 0.0 <= score <= 1.0:
        return None
    return ResilienceScoreSignal(
        resource_id=resource_id,
        score=score,
        experiment_id=experiment_id,
        correlation_id=_correlation_id(payload),
        observed_at=_observed_at(payload),
    )


def build_capacity_sample_event(
    *,
    resource_id: str,
    utilization: float,
    observed_at: str,
    correlation_id: str,
    idempotency_key: str,
    source: str = "fdai.capacity-sampler",
) -> dict[str, Any]:
    """Build a canonical Huginn-ingestible capacity sample event for Freyr."""
    clean_resource = _bounded_string(resource_id)
    clean_observed = _bounded_string(observed_at)
    clean_correlation = _bounded_string(correlation_id)
    clean_key = _bounded_string(idempotency_key)
    clean_source = _bounded_string(source)
    clean_util = _finite_number(utilization)
    if (
        clean_resource is None
        or clean_observed is None
        or clean_correlation is None
        or clean_key is None
        or clean_source is None
        or clean_util is None
        or not 0.0 <= clean_util <= 1.0
    ):
        raise ValueError("capacity sample event fields MUST be valid and bounded")
    return {
        "idempotency_key": clean_key,
        "event_id": f"capacity-sample:{clean_key}",
        "event_type": CAPACITY_SAMPLE_EVENT,
        "source": clean_source,
        "resource_id": clean_resource,
        "correlation_id": clean_correlation,
        "occurred_at": clean_observed,
        "attributes": {
            "resource_id": clean_resource,
            "utilization": clean_util,
            "observed_at": clean_observed,
        },
    }


def build_chaos_schedule_event(
    *,
    experiment_id: str,
    action_type: str,
    targets: Sequence[str],
    correlation_id: str,
    idempotency_key: str,
    occurred_at: str,
    source: str = "fdai.chaos-scheduler",
) -> dict[str, Any]:
    """Build a canonical Huginn-ingestible chaos schedule event for Loki."""
    clean_experiment = _bounded_string(experiment_id)
    clean_action = _bounded_string(action_type)
    clean_correlation = _bounded_string(correlation_id)
    clean_key = _bounded_string(idempotency_key)
    clean_occurred = _bounded_string(occurred_at)
    clean_source = _bounded_string(source)
    if (
        clean_experiment is None
        or clean_action is None
        or clean_action not in CHAOS_ACTION_TYPES
        or clean_correlation is None
        or clean_key is None
        or clean_occurred is None
        or clean_source is None
        or isinstance(targets, str | bytes)
        or not 1 <= len(targets) <= _MAX_TARGETS
    ):
        raise ValueError("chaos schedule event fields MUST be valid and bounded")
    clean_targets = tuple(_bounded_string(item) for item in targets)
    if any(item is None for item in clean_targets) or len(set(clean_targets)) != len(clean_targets):
        raise ValueError("chaos schedule targets MUST be unique and canonical")
    target_tuple = tuple(item for item in clean_targets if item is not None)
    return {
        "idempotency_key": clean_key,
        "event_id": f"chaos-schedule:{clean_key}",
        "event_type": CHAOS_SCHEDULE_EVENT,
        "source": clean_source,
        "resource_id": target_tuple[0],
        "correlation_id": clean_correlation,
        "occurred_at": clean_occurred,
        "attributes": {
            "experiment_id": clean_experiment,
            "action_type": clean_action,
            "targets": list(target_tuple),
        },
    }


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
    raw_envelope = payload.get("resource_id")
    raw_attribute = attributes.get("resource_id")
    envelope_resource = _bounded_string(raw_envelope, required=False)
    attribute_resource = _bounded_string(raw_attribute, required=False)
    if raw_attribute is not None and attribute_resource is None:
        return True
    if raw_envelope is not None and envelope_resource is None:
        return True
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
    "COST_OPTIMIZATION_EVENT",
    "RESILIENCE_SCORE_EVENT",
    "SPECIALIST_EVENT_PREFIX",
    "CapacitySampleSignal",
    "ChaosScheduleSignal",
    "CostSampleSignal",
    "CostOptimizationSignal",
    "ResilienceScoreSignal",
    "build_capacity_sample_event",
    "build_chaos_schedule_event",
    "has_resource_id_conflict",
    "parse_capacity_sample",
    "parse_capacity_graduation_evidence",
    "parse_chaos_schedule",
    "parse_cost_sample",
    "parse_cost_optimization",
    "parse_resilience_score",
]
