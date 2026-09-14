"""Build inert single-axis plans only from complete current authorized evidence."""

from __future__ import annotations

from datetime import datetime, timedelta

from fdai_service_contracts.alert_noise import AlertEvidence, AlertRule, NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt
from fdai_service_contracts.alert_noise_plan import (
    AlertChangePlan,
    AlertRollbackBaseline,
    AlertTreatment,
)


class AlertPlanHeld(ValueError):  # noqa: N818 - preserve the public exception name
    """A stable, content-free reason why no alert change can be proposed."""


def plan_alert_change(
    evidence: AlertEvidence,
    treatment: AlertTreatment,
    *,
    policy: NoisePolicy,
    requester_ref: str,
    now: datetime,
    evaluation_receipt: EvaluationReceipt | None = None,
) -> AlertChangePlan:
    """Build a review-only commitment; a plan is neither approval nor promotion."""
    if now.tzinfo is None or not evidence.stamp.current_at(now):
        raise AlertPlanHeld("stale_evidence")
    if evidence.stamp.coverage != "complete":
        raise AlertPlanHeld("evidence_incomplete")
    rule = next((rule for rule in evidence.rules if rule.ref == treatment.target_ref), None)
    if rule is None:
        raise AlertPlanHeld("target_not_observed")
    _check_rule(rule)
    groups = {group.ref: group for group in evidence.groups}
    audiences = {audience.ref: audience for audience in evidence.audiences}
    locks = {rule.ref, rule.resource_ref}
    services = {rule.service_ref}
    effective_refs = set(rule.group_refs)
    for processing in evidence.processing_rules:
        if not processing.semantics_complete:
            raise AlertPlanHeld("processing_semantics_unknown")
        if rule.ref in processing.rule_refs:
            locks.add(processing.ref)
            if processing.enabled:
                if processing.action == "suppress":
                    raise AlertPlanHeld("overlapping_suppression")
                effective_refs.update(processing.group_refs)
    if treatment.kind == "routing":
        if treatment.remove_group_ref not in rule.group_refs:
            raise AlertPlanHeld("routing_source_mismatch")
        if treatment.replacement_group_ref is None:
            raise AlertPlanHeld("routing_replacement_missing")
        effective_refs.add(treatment.replacement_group_ref)
        if treatment.replacement_group_ref in rule.group_refs:
            raise AlertPlanHeld("routing_replacement_already_bound")
    for group_ref in effective_refs:
        group = groups.get(group_ref)
        if group is None or not group.reverse_complete:
            raise AlertPlanHeld("group_dependencies_incomplete")
        if group.automation_refs:
            raise AlertPlanHeld("automation_path_protected")
        if not group.audience_refs:
            raise AlertPlanHeld("audience_empty")
        locks.add(group.ref)
        for dependent_ref in group.rule_refs:
            dependent = next((item for item in evidence.rules if item.ref == dependent_ref), None)
            if dependent is None:
                raise AlertPlanHeld("dependent_outside_scope")
            _check_rule(dependent)
            locks.add(dependent.ref)
            services.add(dependent.service_ref)
        for audience_ref in group.audience_refs:
            audience = audiences.get(audience_ref)
            if audience is None or audience.coverage != "complete":
                raise AlertPlanHeld("audience_incomplete")
            if not audience.member_refs:
                raise AlertPlanHeld("audience_empty")
            if not audience.primary_verified or not audience.backup_verified:
                raise AlertPlanHeld("responder_coverage_missing")
            locks.add(audience.ref)
    if not effective_refs:
        raise AlertPlanHeld("no_delivery_path")
    action_type = "ops.update-alert-routing"
    target_revision = rule.revision
    baseline = AlertRollbackBaseline(rule=rule)
    expires_at = now + timedelta(hours=24)
    if treatment.kind == "suppression":
        if not evidence.independent_collection:
            raise AlertPlanHeld("independent_collection_missing")
        target = next(
            (
                item
                for item in evidence.processing_rules
                if item.ref == treatment.processing_rule_ref
            ),
            None,
        )
        if target is None or target.action != "suppress" or target.enabled:
            raise AlertPlanHeld("processing_target_not_inert")
        if set(target.rule_refs) != {rule.ref}:
            raise AlertPlanHeld("processing_target_scope_mismatch")
        starts, ends = treatment.starts_at, treatment.ends_at
        if starts is None or ends is None:
            raise AlertPlanHeld("suppression_window_missing")
        if starts < now + timedelta(seconds=policy.propagation_seconds):
            raise AlertPlanHeld("propagation_budget_insufficient")
        if (ends - starts).total_seconds() > policy.max_suppression_seconds:
            raise AlertPlanHeld("suppression_window_exceeds_policy")
        if ends + timedelta(seconds=1800) > expires_at:
            raise AlertPlanHeld("suppression_deadline_does_not_fit")
        locks.add(target.ref)
        target_revision = target.revision
        baseline = AlertRollbackBaseline(rule=rule, processing_rule=target)
        action_type = "ops.set-alert-notification-window"
    if treatment.kind == "evaluation":
        if (
            rule.kind not in {"metric", "log"}
            or rule.evaluation is None
            or treatment.evaluation is None
        ):
            raise AlertPlanHeld("evaluation_kind_unsupported")
        changed = [
            key
            for key, value in rule.evaluation.model_dump().items()
            if treatment.evaluation.model_dump()[key] != value
        ]
        if len(changed) != 1 or changed[0] != "threshold":
            raise AlertPlanHeld("evaluation_requires_single_axis")
        if evaluation_receipt is None:
            raise AlertPlanHeld("evaluation_validation_missing")
        if (
            not isinstance(evaluation_receipt, EvaluationReceipt)
            or not evaluation_receipt.accepted
            or evaluation_receipt.rule_ref != rule.ref
            or evaluation_receipt.rule_revision != rule.revision
            or evaluation_receipt.baseline != rule.evaluation
            or evaluation_receipt.treatment != treatment.evaluation
            or not evaluation_receipt.evaluated_at <= now < evaluation_receipt.expires_at
        ):
            raise AlertPlanHeld("evaluation_validation_mismatch")
        action_type = "ops.tune-alert-evaluation"
    return AlertChangePlan.model_validate(
        {
            "action_type": action_type,
            "tenant_ref": evidence.stamp.tenant_ref,
            "scope_ref": evidence.stamp.scope_ref,
            "requester_ref": requester_ref,
            "evidence_digest": digest_record(evidence),
            "policy_digest": digest_record(policy),
            "target_revision": target_revision,
            "treatment": treatment,
            "service_refs": tuple(sorted(services)),
            "lock_refs": tuple(sorted(locks)),
            "created_at": now,
            "expires_at": expires_at,
            "max_execution_seconds": 300,
            "max_observation_seconds": 3600,
            "max_recovery_seconds": 1800,
            "rollback_ref": digest_record(baseline),
            "evaluation_receipt_digest": (
                digest_record(evaluation_receipt) if evaluation_receipt else None
            ),
        }
    )


def _check_rule(rule: AlertRule) -> None:
    if rule.protected:
        raise AlertPlanHeld("protected_alert")
    if rule.active_incident:
        raise AlertPlanHeld("active_incident_dependency")
    if not rule.enabled:
        raise AlertPlanHeld("disabled_detector")
    if not rule.iac_owned:
        raise AlertPlanHeld("iac_ownership_missing")
    if not rule.ownership_verified:
        raise AlertPlanHeld("service_ownership_missing")
