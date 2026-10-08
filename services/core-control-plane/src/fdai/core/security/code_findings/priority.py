"""First-match priority policy over severity, confidence, exposure, and threat intelligence.

Priority orders remediation work and sets a due interval. It is the only place where known
exploitation (KEV) and runtime exposure influence the outcome; severity stays intrinsic.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.security.code_findings.models import PriorityAssignment
from fdai.rule_catalog.code_security import (
    BAND_ORDER,
    CONFIDENCE_ORDER,
    Confidence,
    Exposure,
    PriorityCondition,
    PriorityPolicy,
    SeverityBand,
)


@dataclass(frozen=True, slots=True)
class PriorityInput:
    floor: SeverityBand
    ceiling: SeverityBand
    confidence: Confidence
    exposure: Exposure
    known_exploited: bool


def _matches(condition: PriorityCondition, item: PriorityInput) -> bool:
    if condition.kev is not None and condition.kev != item.known_exploited:
        return False
    if condition.exposure_in is not None and item.exposure not in condition.exposure_in:
        return False
    if condition.floor_at_least is not None and (
        BAND_ORDER[item.floor] < BAND_ORDER[condition.floor_at_least]
    ):
        return False
    if condition.ceiling_at_least is not None and (
        BAND_ORDER[item.ceiling] < BAND_ORDER[condition.ceiling_at_least]
    ):
        return False
    return condition.confidence_at_least is None or (
        CONFIDENCE_ORDER[item.confidence] >= CONFIDENCE_ORDER[condition.confidence_at_least]
    )


def assign_priority(item: PriorityInput, policy: PriorityPolicy) -> PriorityAssignment:
    """Return the first matching rule's priority, or the policy default."""
    for rule in policy.rules:
        if _matches(rule.when, item):
            return PriorityAssignment(rule.priority, rule.due_days, rule.id, policy.version)
    return PriorityAssignment(
        policy.default.priority, policy.default.due_days, "default", policy.version
    )


__all__ = ["PriorityInput", "assign_priority"]
