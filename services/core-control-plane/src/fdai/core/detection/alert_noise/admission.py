"""Pure exact-plan admission and independently observed effect classification."""

from __future__ import annotations

from datetime import datetime, timedelta

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
    AlertEffectObservation,
)


def admission_reasons(
    plan: AlertChangePlan,
    *,
    approvals: tuple[AlertApproval, ...],
    evidence: AlertDispatchEvidence,
    now: datetime,
) -> tuple[str, ...]:
    """Return every failed gate; trusted ports, not request bodies, supply inputs."""
    reasons: set[str] = set()
    digest = digest_record(plan)
    if now.tzinfo is None:
        return ("clock_invalid",)
    if not plan.created_at <= now < plan.expires_at:
        reasons.add("plan_expired")
    if not evidence.evaluated_at <= now < evidence.valid_until:
        reasons.add("admission_expired")
    if (
        evidence.plan_digest != digest
        or evidence.evidence_digest != plan.evidence_digest
        or evidence.policy_digest != plan.policy_digest
        or evidence.target_revision != plan.target_revision
    ):
        reasons.add("admission_binding_mismatch")
    if evidence.synthetic:
        reasons.add("synthetic_evidence")
    for field, required in (
        ("dependencies_current", evidence.dependencies_current),
        ("actors_current", evidence.actors_current),
        ("observer_ready", evidence.observer_ready),
        ("recovery_ready", evidence.recovery_ready),
        ("writer_fence_missing", bool(evidence.writer_fence_ref)),
        ("audit_intent_missing", bool(evidence.audit_intent_ref)),
        ("recovery_admission_missing", bool(evidence.recovery_admission_ref)),
        ("promotion_missing", bool(evidence.promotion_digest)),
    ):
        if not required:
            reasons.add(field)
    if evidence.kill_switch:
        reasons.add("kill_switch_active")
    if evidence.mode != "enforce":
        reasons.add("shadow_only")
    owners: set[str] = set()
    change_owners: set[str] = set()
    services: set[str] = set()
    seen: set[str] = set()
    end = now + timedelta(
        seconds=plan.max_execution_seconds
        + plan.max_observation_seconds
        + plan.max_recovery_seconds
    )
    if (
        end > plan.expires_at
        or evidence.authorization_until is None
        or end > evidence.authorization_until
    ):
        reasons.add("deadline_does_not_fit")
    if (
        plan.treatment.ends_at is not None
        and plan.treatment.ends_at + timedelta(seconds=plan.max_recovery_seconds) > end
    ):
        end = plan.treatment.ends_at + timedelta(seconds=plan.max_recovery_seconds)
        if (
            end > plan.expires_at
            or evidence.authorization_until is None
            or end > evidence.authorization_until
        ):
            reasons.add("deadline_does_not_fit")
    for approval in approvals:
        if approval.principal_ref in seen:
            reasons.add("duplicate_approver")
        seen.add(approval.principal_ref)
        if approval.principal_ref in {plan.requester_ref, evidence.executor_ref}:
            reasons.add("self_approval")
        if (
            approval.plan_digest != digest
            or approval.tenant_ref != plan.tenant_ref
            or approval.scope_ref != plan.scope_ref
        ):
            reasons.add("approval_binding_mismatch")
        if (
            not plan.created_at <= approval.decided_at <= now < approval.expires_at
            or end > approval.expires_at
        ):
            reasons.add("approval_expired")
        if approval.decision != "approved":
            reasons.add("approval_rejected")
        if approval.lane == "service_owner":
            owners.add(approval.principal_ref)
            services.update(approval.service_refs)
        else:
            change_owners.add(approval.principal_ref)
    if not owners or not change_owners or len(owners | change_owners) < 2:
        reasons.add("independent_quorum_missing")
    if not set(plan.service_refs).issubset(services):
        reasons.add("service_approval_missing")
    return tuple(sorted(reasons))


def effect_outcome(
    plan: AlertChangePlan,
    observation: AlertEffectObservation,
    *,
    dispatch_ref: str,
    dispatched_at: datetime,
    now: datetime,
) -> str:
    """Classify only an exact independently supplied receipt; no executor success shortcut."""
    if (
        observation.plan_digest != digest_record(plan)
        or observation.dispatch_ref != dispatch_ref
        or observation.window_start < dispatched_at
        or observation.recorded_at > now
        or observation.synthetic
        or observation.coverage != "complete"
    ):
        return "held"
    if not all(
        (
            observation.configuration_matches,
            observation.collection_continues,
            observation.protected_paths_preserved,
            observation.response_deadlines_preserved,
        )
    ):
        return "recovery_required"
    if observation.failures or observation.missed_incidents:
        return "recovery_required"
    if not observation.eligible_events or not observation.expected_delivery_observed:
        return "unscorable"
    if (
        observation.window_end - observation.window_start
    ).total_seconds() < plan.max_observation_seconds:
        return "held"
    return "recovered" if observation.recovery else "verified"
