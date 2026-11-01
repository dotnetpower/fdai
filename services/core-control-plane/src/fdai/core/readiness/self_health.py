"""Deterministic self-health alert policy over source-qualified observations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from fdai_service_contracts.self_health import SelfHealthSignalName as SelfHealthSignal


class SelfHealthCatalogError(ValueError):
    """Raised when the complete self-health policy cannot be established."""


class SelfHealthComparison(StrEnum):
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


class SelfHealthOwnerLane(StrEnum):
    OPERATIONAL = "operational"
    HUMAN_APPROVAL = "human_approval"


@dataclass(frozen=True, slots=True)
class SelfHealthSignalPolicy:
    signal: SelfHealthSignal
    metric: str
    comparison: SelfHealthComparison
    threshold: Decimal
    maximum_age_seconds: int
    owner_lane: SelfHealthOwnerLane
    route: str
    fallback: str

    def __post_init__(self) -> None:
        if not self.metric.strip() or self.metric != self.metric.strip():
            raise SelfHealthCatalogError("self-health metric MUST be exact non-empty text")
        if not self.threshold.is_finite():
            raise SelfHealthCatalogError("self-health threshold MUST be finite")
        if isinstance(self.maximum_age_seconds, bool) or self.maximum_age_seconds < 1:
            raise SelfHealthCatalogError("self-health maximum age MUST be positive")
        for value in (self.route, self.fallback):
            if not value.strip() or value != value.strip():
                raise SelfHealthCatalogError("self-health routing values MUST be exact")


@dataclass(frozen=True, slots=True)
class SelfHealthObservation:
    signal: SelfHealthSignal
    value: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not self.value.is_finite():
            raise ValueError("self-health observation value MUST be finite")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("self-health observation time MUST be timezone-aware")
        if not self.source.strip() or self.source != self.source.strip():
            raise ValueError("self-health observation source MUST be exact")


@dataclass(frozen=True, slots=True)
class SelfHealthDecision:
    signal: SelfHealthSignal
    alert: bool
    reason: str
    owner_lane: SelfHealthOwnerLane
    route: str
    fallback: str
    observed_value: Decimal
    threshold: Decimal
    execution_authority: bool = False


@dataclass(frozen=True, slots=True)
class SelfHealthCatalog:
    version: int
    policies: Mapping[SelfHealthSignal, SelfHealthSignalPolicy]

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version < 1:
            raise SelfHealthCatalogError("self-health catalog version MUST be positive")
        if set(self.policies) != set(SelfHealthSignal):
            missing = sorted(signal.value for signal in set(SelfHealthSignal) - set(self.policies))
            extra = sorted(str(signal) for signal in set(self.policies) - set(SelfHealthSignal))
            raise SelfHealthCatalogError(
                f"self-health catalog coverage is invalid: missing={missing}, extra={extra}"
            )

    def evaluate(
        self,
        observation: SelfHealthObservation,
        *,
        now: datetime,
    ) -> SelfHealthDecision:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("self-health evaluation time MUST be timezone-aware")
        policy = self.policies[observation.signal]
        age_seconds = (now - observation.observed_at).total_seconds()
        if age_seconds < 0:
            return _decision(policy, observation, alert=True, reason="observation_from_future")
        if age_seconds > policy.maximum_age_seconds:
            return _decision(policy, observation, alert=True, reason="observation_stale")
        if policy.comparison is SelfHealthComparison.GREATER_THAN:
            alert = observation.value > policy.threshold
        else:
            alert = observation.value < policy.threshold
        return _decision(
            policy,
            observation,
            alert=alert,
            reason="threshold_breached" if alert else "healthy",
        )


def load_self_health_catalog(
    path: Path,
    *,
    route_fallbacks: Mapping[str, str],
) -> SelfHealthCatalog:
    with path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if not isinstance(raw, Mapping):
        raise SelfHealthCatalogError("self-health catalog MUST be a mapping")
    catalog_raw = raw.get("catalog")
    if not isinstance(catalog_raw, Mapping):
        raise SelfHealthCatalogError("self-health catalog root is invalid")
    version = catalog_raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise SelfHealthCatalogError("self-health catalog version is invalid")
    signals_raw = catalog_raw.get("signals")
    if not isinstance(signals_raw, Mapping):
        raise SelfHealthCatalogError("self-health catalog signals are invalid")
    policies: dict[SelfHealthSignal, SelfHealthSignalPolicy] = {}
    for signal_name, policy_raw in signals_raw.items():
        try:
            signal = SelfHealthSignal(signal_name)
        except (TypeError, ValueError) as exc:
            raise SelfHealthCatalogError("self-health signal is unknown") from exc
        if signal in policies or not isinstance(policy_raw, Mapping):
            raise SelfHealthCatalogError("self-health signal policy is invalid")
        policy = _policy(signal, policy_raw)
        if route_fallbacks.get(policy.route) != policy.fallback:
            raise SelfHealthCatalogError(
                f"self-health route fallback does not match notification matrix: {policy.route}"
            )
        policies[signal] = policy
    return SelfHealthCatalog(version=version, policies=MappingProxyType(policies))


def _policy(
    signal: SelfHealthSignal,
    raw: Mapping[object, object],
) -> SelfHealthSignalPolicy:
    expected = {
        "metric",
        "comparison",
        "threshold",
        "maximum_age_seconds",
        "owner_lane",
        "route",
        "fallback",
    }
    if set(raw) != expected:
        raise SelfHealthCatalogError(f"self-health policy fields are invalid: {signal.value}")
    try:
        threshold = Decimal(str(raw["threshold"]))
        maximum_age_seconds = raw["maximum_age_seconds"]
        if isinstance(maximum_age_seconds, bool) or not isinstance(maximum_age_seconds, int):
            raise ValueError
        return SelfHealthSignalPolicy(
            signal=signal,
            metric=_text(raw["metric"]),
            comparison=SelfHealthComparison(_text(raw["comparison"])),
            threshold=threshold,
            maximum_age_seconds=maximum_age_seconds,
            owner_lane=SelfHealthOwnerLane(_text(raw["owner_lane"])),
            route=_text(raw["route"]),
            fallback=_text(raw["fallback"]),
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SelfHealthCatalogError(f"self-health policy is invalid: {signal.value}") from exc


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value


def _decision(
    policy: SelfHealthSignalPolicy,
    observation: SelfHealthObservation,
    *,
    alert: bool,
    reason: str,
) -> SelfHealthDecision:
    return SelfHealthDecision(
        signal=policy.signal,
        alert=alert,
        reason=reason,
        owner_lane=policy.owner_lane,
        route=policy.route,
        fallback=policy.fallback,
        observed_value=observation.value,
        threshold=policy.threshold,
    )


__all__ = [
    "SelfHealthCatalog",
    "SelfHealthCatalogError",
    "SelfHealthComparison",
    "SelfHealthDecision",
    "SelfHealthObservation",
    "SelfHealthOwnerLane",
    "SelfHealthSignal",
    "SelfHealthSignalPolicy",
    "load_self_health_catalog",
]
