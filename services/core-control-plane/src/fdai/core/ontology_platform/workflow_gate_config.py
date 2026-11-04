"""Load the reviewed configuration of workflow ontology function gates.

The configuration selects thresholds and look-back windows. It never selects evidence, so a
missing or malformed block keeps its gate shut instead of falling back to a default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from .decision_functions import (
    BLAST_RADIUS_FUNCTION_NAME,
    CHANGE_RISK_FUNCTION_NAME,
    COST_OF_DELAY_FUNCTION_NAME,
    MAX_DEPTH,
)

_BLAST_TIERS: Final = ("low", "medium", "high")
_MAX_LOOKBACK_DAYS: Final = 365
_MAX_AGE_SECONDS: Final = 3_600
_MAX_OBSERVATION_AGE_HOURS: Final = 24 * 31


@dataclass(frozen=True, slots=True)
class BlastRadiusGateConfig:
    max_tier: str
    max_depth: int


@dataclass(frozen=True, slots=True)
class ChangeRiskGateConfig:
    max_tier: str
    failed_change_lookback: timedelta
    recovery_rehearsal_lookback: timedelta
    dry_run_lookback: timedelta


@dataclass(frozen=True, slots=True)
class CostOfDelayGateConfig:
    metric: str
    delay_hours: int
    min_total_amount: Decimal
    max_observation_age: timedelta


@dataclass(frozen=True, slots=True)
class OntologyGateConfig:
    max_reading_age: timedelta
    blast_radius: BlastRadiusGateConfig | None
    change_risk: ChangeRiskGateConfig | None
    cost_of_delay: CostOfDelayGateConfig | None

    def gate_arguments(self) -> dict[str, dict[str, Any]]:
        """Return the fixed registry arguments of every configured gate."""

        arguments: dict[str, dict[str, Any]] = {}
        if self.blast_radius is not None:
            arguments[BLAST_RADIUS_FUNCTION_NAME] = {"max_tier": self.blast_radius.max_tier}
        if self.change_risk is not None:
            arguments[CHANGE_RISK_FUNCTION_NAME] = {"max_tier": self.change_risk.max_tier}
        if self.cost_of_delay is not None:
            arguments[COST_OF_DELAY_FUNCTION_NAME] = {
                "delay_hours": self.cost_of_delay.delay_hours,
                "min_total_amount": format(self.cost_of_delay.min_total_amount, "f"),
            }
        return arguments


def load_ontology_gate_config(raw: object) -> OntologyGateConfig:
    """Validate the configuration, failing on any malformed value."""

    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0":
        raise ValueError("workflow ontology gate config schema_version MUST be 1.0")
    allowed = {
        "schema_version",
        "max_reading_age_seconds",
        BLAST_RADIUS_FUNCTION_NAME,
        CHANGE_RISK_FUNCTION_NAME,
        COST_OF_DELAY_FUNCTION_NAME,
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"workflow ontology gate config has unknown key: {unknown[0]}")
    age = _bounded_int(
        raw.get("max_reading_age_seconds"), "max_reading_age_seconds", 1, _MAX_AGE_SECONDS
    )
    return OntologyGateConfig(
        max_reading_age=timedelta(seconds=age),
        blast_radius=_blast_radius(raw.get(BLAST_RADIUS_FUNCTION_NAME)),
        change_risk=_change_risk(raw.get(CHANGE_RISK_FUNCTION_NAME)),
        cost_of_delay=_cost_of_delay(raw.get(COST_OF_DELAY_FUNCTION_NAME)),
    )


def _block(value: object, name: str, keys: set[str]) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{name} MUST be an object with exactly: {', '.join(sorted(keys))}")
    return value


def _blast_radius(value: object) -> BlastRadiusGateConfig | None:
    block = _block(value, BLAST_RADIUS_FUNCTION_NAME, {"max_tier", "max_depth"})
    if block is None:
        return None
    return BlastRadiusGateConfig(
        max_tier=_tier(block["max_tier"]),
        max_depth=_bounded_int(block["max_depth"], "max_depth", 1, MAX_DEPTH),
    )


def _change_risk(value: object) -> ChangeRiskGateConfig | None:
    block = _block(
        value,
        CHANGE_RISK_FUNCTION_NAME,
        {
            "max_tier",
            "failed_change_lookback_days",
            "recovery_rehearsal_lookback_days",
            "dry_run_lookback_days",
        },
    )
    if block is None:
        return None
    return ChangeRiskGateConfig(
        max_tier=_tier(block["max_tier"]),
        failed_change_lookback=_days(block["failed_change_lookback_days"]),
        recovery_rehearsal_lookback=_days(block["recovery_rehearsal_lookback_days"]),
        dry_run_lookback=_days(block["dry_run_lookback_days"]),
    )


def _cost_of_delay(value: object) -> CostOfDelayGateConfig | None:
    block = _block(
        value,
        COST_OF_DELAY_FUNCTION_NAME,
        {"metric", "delay_hours", "min_total_amount", "max_observation_age_hours"},
    )
    if block is None:
        return None
    metric = block["metric"]
    if not isinstance(metric, str) or not metric.strip():
        raise ValueError("cost of delay metric MUST be non-empty text")
    amount = block["min_total_amount"]
    if not isinstance(amount, str):
        raise ValueError("min_total_amount MUST be a decimal string")
    try:
        minimum = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("min_total_amount MUST be a decimal string") from exc
    if not minimum.is_finite() or minimum < 0:
        raise ValueError("min_total_amount MUST be a non-negative decimal")
    return CostOfDelayGateConfig(
        metric=metric.strip(),
        delay_hours=_bounded_int(block["delay_hours"], "delay_hours", 1, 720),
        min_total_amount=minimum,
        max_observation_age=timedelta(
            hours=_bounded_int(
                block["max_observation_age_hours"],
                "max_observation_age_hours",
                1,
                _MAX_OBSERVATION_AGE_HOURS,
            )
        ),
    )


def _tier(value: object) -> str:
    if value not in _BLAST_TIERS:
        raise ValueError(f"max_tier MUST be one of {', '.join(_BLAST_TIERS)}")
    return str(value)


def _days(value: object) -> timedelta:
    return timedelta(days=_bounded_int(value, "look-back days", 1, _MAX_LOOKBACK_DAYS))


def _bounded_int(value: object, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} MUST be an integer between {low} and {high}")
    return value


__all__ = [
    "BlastRadiusGateConfig",
    "ChangeRiskGateConfig",
    "CostOfDelayGateConfig",
    "OntologyGateConfig",
    "load_ontology_gate_config",
]
