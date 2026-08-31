"""Pure mapping and normalization helpers for Forseti's judge behavior."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.decision_case import (
    DomainDecisionProjection,
    DomainOptionEvidence,
    ObjectiveEffect,
)
from fdai.core.operational_context import SourceFreshness
from fdai.core.operational_planning import SpecialistPlanningProjection

_DecisionProjection = DomainDecisionProjection | SpecialistPlanningProjection

# Hard caps on the runtime-grounded evidence one event may carry, so a
# malformed producer cannot inflate an arbitration beyond bounded review.
MAX_DOMAIN_EVIDENCE_ENTRIES = 8
MAX_DOMAIN_EVIDENCE_REFS = 32
MAX_EVIDENCE_REF_LENGTH = 512

# Lineage marker Forseti mints for a specialist that contributed advice.
# It identifies who spoke, never what the runtime observed, so it may
# accompany canonical lineage but never stand in for it.
_SPECIALIST_MARKER_PREFIX = "specialist:"


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


def domain_option_evidence(raw: object) -> tuple[DomainOptionEvidence, ...]:
    """Parse runtime-grounded option evidence carried on an event.

    Strict and bounded, like :func:`source_freshness`: a malformed entry
    raises rather than silently degrading a conflict to a label
    comparison. Every entry MUST carry lineage that is not merely the
    specialist marker Forseti mints itself, so an arbitration can always
    be traced back to the canonical runtime record it came from.
    """

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("domain_evidence MUST be an array")
    if len(raw) > MAX_DOMAIN_EVIDENCE_ENTRIES:
        raise ValueError("domain_evidence entry count exceeds the hard limit")
    items: list[DomainOptionEvidence] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("domain_evidence entries MUST be objects")
        domain = item.get("domain")
        action_type = item.get("action_type")
        if not isinstance(domain, str) or not domain:
            raise ValueError("domain_evidence domain MUST be a non-empty string")
        if not isinstance(action_type, str) or not action_type:
            raise ValueError("domain_evidence action_type MUST be a non-empty string")
        if domain in seen:
            raise ValueError("domain_evidence MUST carry one entry per domain")
        seen.add(domain)
        items.append(
            DomainOptionEvidence(
                domain=domain,
                action_type=action_type,
                effects=_objective_effects(item.get("effects")),
                evidence_refs=_evidence_refs(item.get("evidence_refs")),
            )
        )
    return tuple(items)


def _objective_effects(raw: object) -> tuple[ObjectiveEffect, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("domain_evidence effects MUST be a non-empty array")
    effects: list[ObjectiveEffect] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("domain_evidence effect entries MUST be objects")
        objective_id = item.get("objective_id")
        metric = item.get("metric")
        window = item.get("observation_window_seconds")
        if not isinstance(objective_id, str) or not isinstance(metric, str):
            raise ValueError("domain_evidence effect identities MUST be strings")
        if isinstance(window, bool) or not isinstance(window, int):
            raise ValueError("domain_evidence observation_window_seconds MUST be an integer")
        effects.append(
            ObjectiveEffect(
                objective_id=objective_id,
                utility=_finite(item.get("utility"), "utility"),
                confidence=_finite(item.get("confidence"), "confidence"),
                metric=metric,
                expected_min=_finite(item.get("expected_min"), "expected_min"),
                expected_max=_finite(item.get("expected_max"), "expected_max"),
                observation_window_seconds=window,
            )
        )
    return tuple(effects)


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"domain_evidence {field} MUST be a number")
    return float(value)


def _evidence_refs(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("domain_evidence evidence_refs MUST be a non-empty array")
    if len(raw) > MAX_DOMAIN_EVIDENCE_REFS:
        raise ValueError("domain_evidence evidence_refs count exceeds the hard limit")
    refs: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item or len(item) > MAX_EVIDENCE_REF_LENGTH:
            raise ValueError("domain_evidence evidence_refs entries MUST be bounded strings")
        refs.append(item)
    if all(ref.startswith(_SPECIALIST_MARKER_PREFIX) for ref in refs):
        raise ValueError("domain_evidence MUST carry lineage beyond the specialist marker")
    return tuple(dict.fromkeys(refs))
