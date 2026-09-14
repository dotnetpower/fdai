"""Reduce frozen alert evidence without inferring delivery, ownership or authority."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fdai_service_contracts.alert_noise import (
    AlertDelivery,
    AlertEvidence,
    Audience,
    NoiseAssessment,
    NoiseFinding,
    NoisePolicy,
    digest_record,
)

from fdai.core.detection.alert_noise.measurement import flapping_transitions, notification_counts


def audience_bounds(audiences: tuple[Audience, ...]) -> tuple[int, int | None, int]:
    """Return verified lower/upper reach and duplicate paths; never invent identity links."""
    known = set().union(*(set(audience.member_refs) for audience in audiences))
    duplicate_paths = sum(len(audience.member_refs) for audience in audiences) - len(known)
    if all(audience.coverage == "complete" for audience in audiences):
        return len(known), len(known), duplicate_paths
    if any(audience.potential_members is None for audience in audiences):
        return len(known), None, duplicate_paths
    unknown = sum(
        (audience.potential_members or 0) - len(audience.member_refs) for audience in audiences
    )
    return len(known), len(known) + unknown, duplicate_paths


def assess_alert_noise(
    evidence: AlertEvidence,
    *,
    policy: NoisePolicy,
    now: datetime,
) -> NoiseAssessment:
    """Produce a scope-bound no-authority report including unavailable denominators."""
    if now.tzinfo is None:
        raise ValueError("assessment clock MUST include a timezone")
    groups = {group.ref: group for group in evidence.groups}
    audience_map = {audience.ref: audience for audience in evidence.audiences}
    by_rule: dict[str, list[AlertDelivery]] = defaultdict(list)
    for item in evidence.deliveries:
        by_rule[item.rule_ref].append(item)
    reasons = set(evidence.stamp.reasons)
    if not evidence.stamp.current_at(now):
        reasons.add("stale_evidence")
    if evidence.delivery_coverage != "complete":
        reasons.add("delivery_coverage_incomplete")
    if evidence.history_coverage != "complete":
        reasons.add("history_coverage_incomplete")
    findings: list[NoiseFinding] = []
    candidate_count = 0
    for rule in sorted(evidence.rules, key=lambda item: item.ref):
        events = by_rule[rule.ref]
        episodes = {item.episode_ref for item in events if item.condition == "fired"}
        destinations: set[str] = set()
        complete = True
        effective_groups = set(rule.group_refs)
        for processing in evidence.processing_rules:
            if rule.ref not in processing.rule_refs or not processing.enabled:
                continue
            if (
                processing.effective_from < evidence.window_end
                and processing.effective_to > evidence.window_start
            ):
                # A historical interval cannot be treated as one static audience snapshot.
                complete = False
                if processing.action == "add":
                    effective_groups.update(processing.group_refs)
        for group_ref in effective_groups:
            group = groups.get(group_ref)
            if group is None:
                complete = False
                continue
            destinations.update(group.audience_refs)
        audiences = tuple(audience_map[ref] for ref in sorted(destinations) if ref in audience_map)
        complete = complete and len(audiences) == len(destinations)
        lower, upper, overlap = audience_bounds(audiences)
        if not complete:
            upper = None
        if lower < policy.min_cohort_size:
            lower_value = None
            upper = None
        else:
            lower_value = lower
        issue_codes: list[str] = []
        if len(episodes) >= policy.burst_threshold:
            issue_codes.append("storm")
        if rule.stateful and flapping_transitions(tuple(events)) >= policy.flapping_threshold:
            issue_codes.append("flapping")
        if overlap:
            issue_codes.append("overlap")
        if any(audience.kind == "role" for audience in audiences):
            issue_codes.append("broad_role")
        if not rule.ownership_verified:
            issue_codes.append("unowned")
        if rule.protected and issue_codes:
            issue_codes.append("protected")
        if not complete or any(audience.coverage != "complete" for audience in audiences):
            issue_codes.append("incomplete")
            reasons.add("routing_coverage_incomplete")
        if issue_codes:
            candidate_count += 1
            if candidate_count > policy.max_candidates:
                reasons.add("candidate_limit_reached")
                continue
        _, delivered, _ = notification_counts(
            tuple(events), complete=evidence.delivery_coverage == "complete"
        )
        for code in issue_codes:
            guidance = {
                "storm": "review-routing",
                "flapping": "review-evaluation",
                "overlap": "review-routing",
                "broad_role": "review-routing",
                "unowned": "review-ownership",
                "protected": "retain-protected",
                "incomplete": "collect-evidence",
            }[code]
            findings.append(
                NoiseFinding.model_validate(
                    {
                        "rule_ref": rule.ref,
                        "service_ref": rule.service_ref,
                        "reason": code,
                        "guidance": "retain-protected" if rule.protected else guidance,
                        "source_episodes": (
                            len(episodes)
                            if episodes or evidence.history_coverage == "complete"
                            else None
                        ),
                        "observed_deliveries": delivered,
                        "potential_recipients_lower": lower_value,
                        "potential_recipients_upper": upper,
                        "duplicate_paths": overlap if lower_value is not None else 0,
                        "protected": rule.protected,
                    }
                )
            )
    source_episodes = {
        (item.rule_ref, item.episode_ref)
        for item in evidence.deliveries
        if item.condition == "fired"
    }
    attempts, confirmed, acknowledgements = notification_counts(
        evidence.deliveries,
        complete=evidence.delivery_coverage == "complete",
    )
    if len(reasons) > 32:
        reasons = {*sorted(reasons)[:31], "evidence_reason_limit_reached"}
    return NoiseAssessment(
        evidence_digest=digest_record(evidence),
        policy_digest=digest_record(policy),
        tenant_ref=evidence.stamp.tenant_ref,
        scope_ref=evidence.stamp.scope_ref,
        observed_at=evidence.stamp.observed_at,
        valid_until=evidence.stamp.valid_until,
        window_start=evidence.window_start,
        window_end=evidence.window_end,
        coverage=(
            "unavailable"
            if evidence.stamp.coverage == "unavailable"
            else ("partial" if reasons else "complete")
        ),
        reasons=tuple(sorted(reasons)),
        source_episodes=(
            len(source_episodes)
            if source_episodes or evidence.history_coverage == "complete"
            else None
        ),
        notification_attempts=attempts,
        confirmed_deliveries=confirmed,
        acknowledgements=acknowledgements,
        findings=tuple(findings),
    )
