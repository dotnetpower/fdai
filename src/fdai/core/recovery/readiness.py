"""Fail-closed recovery readiness and pre-authorization checks."""

from __future__ import annotations

from datetime import datetime, timedelta

from fdai.core.recovery.models import RecoveryPlanRecord, RecoveryPlanStatus, RecoveryReadiness


def evaluate_recovery_readiness(
    plan: RecoveryPlanRecord,
    *,
    now: datetime,
    current_graph_revision: str,
    promoted_action_types: frozenset[str],
    telemetry_sources: frozenset[str],
    required_telemetry_sources: frozenset[str],
    max_rehearsal_age: timedelta,
) -> RecoveryReadiness:
    if now.tzinfo is None or max_rehearsal_age <= timedelta(0):
        raise ValueError("readiness time MUST be aware and rehearsal age MUST be positive")
    reasons: list[str] = []
    if plan.status is not RecoveryPlanStatus.READY:
        reasons.append("plan_not_ready")
    if now > plan.expires_at:
        reasons.append("plan_expired")
    if current_graph_revision != plan.graph_revision:
        reasons.append("graph_revision_changed")
    if now - plan.last_rehearsed_at > max_rehearsal_age:
        reasons.append("rehearsal_stale")
    action_types = {item.action_type_ref for item in plan.actions}
    if not action_types <= promoted_action_types:
        reasons.append("recovery_action_not_promoted")
    if not required_telemetry_sources <= telemetry_sources:
        reasons.append("telemetry_incomplete")
    return RecoveryReadiness(ready=not reasons, reasons=tuple(sorted(reasons)))


def preauthorization_covers(
    plan: RecoveryPlanRecord,
    *,
    target_ids: tuple[str, ...],
    action_versions: tuple[tuple[str, str], ...],
    now: datetime,
    destructive: bool = False,
) -> bool:
    if now.tzinfo is None or now > plan.expires_at or destructive:
        return False
    if not set(target_ids) <= set(plan.direct_target_ids):
        return False
    pinned = {(item.action_type_ref, item.action_type_version) for item in plan.actions}
    return set(action_versions) <= pinned


__all__ = ["evaluate_recovery_readiness", "preauthorization_covers"]
