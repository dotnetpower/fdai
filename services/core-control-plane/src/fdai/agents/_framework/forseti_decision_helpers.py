"""Pure mapping and normalization helpers for Forseti's judge behavior."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.decision_case import DomainDecisionProjection
from fdai.core.operational_context import SourceFreshness
from fdai.core.operational_planning import SpecialistPlanningProjection

_DecisionProjection = DomainDecisionProjection | SpecialistPlanningProjection


def copy_change_assessment(event: Mapping[str, Any], verdict: dict[str, Any]) -> None:
    status = event.get("change_assessment_status")
    if isinstance(status, str):
        verdict["change_assessment_status"] = status
    assessment = event.get("change_assessment")
    if isinstance(assessment, Mapping):
        verdict["change_assessment"] = dict(assessment)


def change_assessment_mapping(event: Mapping[str, Any]) -> dict[str, Any] | None:
    assessment = event.get("change_assessment")
    return dict(assessment) if isinstance(assessment, Mapping) else None


def decision_case_mapping(
    projection: _DecisionProjection,
    change_assessment: Mapping[str, Any] | None,
) -> dict[str, object]:
    mapping = projection.to_mapping()
    if change_assessment is not None:
        mapping["change_assessment"] = dict(change_assessment)
    return mapping


def is_conflict(advice: dict[str, str]) -> bool:
    """Return whether at least two domains recommend distinct actions."""
    active = {
        domain: recommendation
        for domain, recommendation in advice.items()
        if recommendation != "hold"
    }
    return len(active) >= 2 and len(set(active.values())) >= 2


def signal_impact(domain: str, payload: dict[str, Any]) -> float:
    """Read the bounded impact magnitude supplied by a domain specialist."""
    explicit = payload.get("impact")
    if explicit is not None:
        try:
            return max(0.0, min(1.0, float(explicit)))
        except (TypeError, ValueError):
            pass
    if domain == "cost" and "ratio" in payload:
        try:
            return max(0.0, min(1.0, float(payload["ratio"]) - 1.0))
        except (TypeError, ValueError):
            return 1.0
    if domain == "capacity" and "forecast_util" in payload:
        try:
            return max(0.0, min(1.0, float(payload["forecast_util"])))
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def source_freshness(raw: object) -> tuple[SourceFreshness, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("source_freshness MUST be an array")
    items: list[SourceFreshness] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("source_freshness entries MUST be objects")
        source = item.get("source")
        observed_at = item.get("observed_at")
        max_age_seconds = item.get("max_age_seconds")
        if not isinstance(source, str):
            raise ValueError("source_freshness source MUST be a string")
        if not isinstance(observed_at, str):
            raise ValueError("source_freshness observed_at MUST be a timestamp")
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int):
            raise ValueError("source_freshness max_age_seconds MUST be an integer")
        items.append(
            SourceFreshness(
                source=source,
                observed_at=datetime.fromisoformat(observed_at.replace("Z", "+00:00")),
                max_age_seconds=max_age_seconds,
            )
        )
    return tuple(items)
